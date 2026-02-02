"""
סורק פייסבוק אוטומטי עם Playwright
כולל טכניקות הסוואה למניעת זיהוי
Production Ready - עם ניהול שגיאות, stealth, וניקוי אוטומטי
"""

import asyncio
import random
import hashlib
import os
import re
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path

from playwright.async_api import async_playwright, Page, Browser
from playwright_stealth import Stealth

import config
from database import get_db
from candidatMatcher import get_matcher
from responseGenerator import get_generator


def cleanup_old_screenshots(screenshot_dir: Path, max_files: int = 50):
    """
    ניקוי צילומי מסך ישנים כדי למנוע בעיות נפח דיסק

    Args:
        screenshot_dir: תיקיית הצילומים
        max_files: מספר קבצים מקסימלי לשמור
    """
    try:
        if not screenshot_dir.exists():
            return

        # קבלת כל קבצי PNG בתיקייה
        files = list(screenshot_dir.glob("*.png"))

        if len(files) <= max_files:
            return

        # מיון לפי זמן שינוי (ישן ראשון)
        files.sort(key=lambda x: x.stat().st_mtime)

        # מחיקת הקבצים הישנים ביותר
        files_to_delete = len(files) - max_files
        for file in files[:files_to_delete]:
            try:
                file.unlink()
            except Exception:
                pass

        print(f"   🧹 נמחקו {files_to_delete} צילומי מסך ישנים")

    except Exception as e:
        print(f"   ⚠️ שגיאה בניקוי צילומים: {e}")


def clean_author_name(raw_name: str) -> str:
    """
    ניקוי שם מחבר מתווים מיותרים

    Examples:
        "Moshe > Jobs Petah Tikva" -> "Moshe"
        "David Cohen\nFollow\n2 hours" -> "David Cohen"
    """
    if not raw_name:
        return ""

    # הסרת תווים מיוחדים וחיתוך לפני סימנים
    name = raw_name.strip()

    # חיתוך לפני ">"
    if ">" in name:
        name = name.split(">")[0].strip()

    # חיתוך לפני שורה חדשה
    if "\n" in name:
        name = name.split("\n")[0].strip()

    # חיתוך לפני "·" (נקודה אמצעית של פייסבוק)
    if "·" in name:
        name = name.split("·")[0].strip()

    # הסרת רווחים כפולים
    name = re.sub(r'\s+', ' ', name)

    # אם השם ארוך מדי, כנראה שזה לא שם אמיתי
    if len(name) > 50:
        return ""

    return name


class FacebookScraper:
    """סורק קבוצות פייסבוק ומגיב למועמדים"""
    
    def __init__(self):
        self.db = get_db()
        self.matcher = get_matcher()
        self.generator = get_generator()
        self.playwright = None
        self.context = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.is_logged_in = False
    
    async def start(self):
        """הפעלת הדפדפן והתחברות"""
        # Store playwright instance on self so it is not garbage-collected
        # while the browser session is alive.  Losing this reference causes
        # the underlying browser process to be torn down, which is the root
        # cause of "Target page, context or browser has been closed" errors
        # when scanning the second group onwards.
        self.playwright = await async_playwright().start()

        # נתיב לשמירת הסשן
        user_data_dir = config.DATA_DIR / "browser_session"
        user_data_dir.mkdir(exist_ok=True)

        print(f"💾 משתמש בסשן שמור: {user_data_dir}")

        # בחירת User Agent אקראי לכל הפעלה (stealth)
        user_agent = config.get_random_user_agent()
        print(f"🕵️ User Agent: {user_agent[:50]}...")

        # פתיחת דפדפן עם persistent context (שומר cookies וסשן)
        # launch_persistent_context returns a BrowserContext directly
        # (not a Browser).  context.browser is None for persistent contexts,
        # so we must store the context itself to keep it alive.
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=config.BROWSER_SETTINGS['headless'],
            slow_mo=config.BROWSER_SETTINGS['slow_mo'],
            viewport=config.BROWSER_SETTINGS['viewport'],
            user_agent=user_agent,
            args=["--start-maximized"]
        )

        self.browser = self.context.browser
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

        # החלת טכניקות הסוואה
        stealth = Stealth()
        await stealth.apply_stealth_async(self.page)

        print("✅ דפדפן הופעל בהצלחה")
    
    async def _is_logged_in_check(self) -> bool:
        """בדיקה אמיתית אם מחוברים לפייסבוק - לא רק לפי URL"""
        try:
            # חיפוש אלמנטים שמופיעים רק כשמחוברים
            logged_in_selectors = [
                'div[role="navigation"]',           # סרגל ניווט עליון
                'a[aria-label="Profile"]',           # קישור לפרופיל
                'a[aria-label="פרופיל"]',
                'svg[aria-label="Your profile"]',
                'div[aria-label="Facebook"]',        # לוגו מחובר
                'input[aria-label="Search Facebook"]',
                'input[aria-label="חיפוש בפייסבוק"]',
            ]
            for sel in logged_in_selectors:
                if await self.page.locator(sel).count() > 0:
                    return True

            # בדיקה שלילית: אם יש טופס login בעמוד
            login_form = await self.page.locator('input[name="email"], input[name="pass"], #loginbutton, button:has-text("Log in"), button:has-text("Log In")').count()
            if login_form > 0:
                return False

            # אם אין סימנים ברורים, נבדוק URL
            url = self.page.url
            if 'login' in url.lower() or 'checkpoint' in url.lower():
                return False

            return True
        except:
            return False

    async def login_to_facebook(self):
        """התחברות לפייסבוק"""
        try:
            print("🔐 בודק התחברות לפייסבוק...")

            # מעבר לפייסבוק
            await self.page.goto('https://www.facebook.com/', wait_until='domcontentloaded', timeout=60000)
            await self.human_delay(3, 5)

            # בדיקה אם כבר מחוברים
            print("🔍 בודק אם כבר מחובר...")
            if await self._is_logged_in_check():
                print("✅ כבר מחובר לפייסבוק!")
                self.is_logged_in = True
                return True

            # לא מחוברים - ננסה להתחבר עם הפרטים מ-.env
            email = config.FACEBOOK_CREDENTIALS.get('email', '')
            password = config.FACEBOOK_CREDENTIALS.get('password', '')

            if email and password:
                print("🔑 מתחבר עם פרטי חשבון מ-.env...")
                try:
                    # מילוי שדה אימייל
                    email_field = self.page.locator('input[name="email"], #email')
                    await email_field.first.click(timeout=5000)
                    await email_field.first.fill('')
                    await self.human_type(email_field.first, email)
                    await self.human_delay(0.5, 1)

                    # מילוי שדה סיסמה
                    pass_field = self.page.locator('input[name="pass"], #pass')
                    await pass_field.first.click(timeout=5000)
                    await pass_field.first.fill('')
                    await self.human_type(pass_field.first, password)
                    await self.human_delay(0.5, 1)

                    # לחיצה על כפתור התחברות
                    login_btn = self.page.locator('button[name="login"], #loginbutton, button[type="submit"]')
                    await login_btn.first.click(timeout=5000)

                    # המתנה לטעינת העמוד אחרי התחברות
                    print("⏳ ממתין להתחברות...")
                    await self.human_delay(5, 8)

                    # בדיקה אם ההתחברות הצליחה
                    if await self._is_logged_in_check():
                        print("✅ התחברות הצליחה!")
                        self.is_logged_in = True
                        return True

                    # אולי יש אימות דו-שלבי או checkpoint
                    current_url = self.page.url
                    if 'checkpoint' in current_url.lower() or 'two_step' in current_url.lower():
                        print("\n⚠️ נדרש אימות דו-שלבי!")
                        print("   אנא השלם את האימות בחלון הדפדפן...")
                    else:
                        print("⚠️ ההתחברות האוטומטית נכשלה")

                except Exception as e:
                    print(f"⚠️ שגיאה בהתחברות אוטומטית: {str(e)[:60]}")

            # fallback - המתנה להתחברות ידנית
            print("\n" + "="*60)
            print("⚠️  אנא התחבר ידנית בחלון הדפדפן")
            print("="*60)
            print("⏳ ממתין להתחברות... (60 שניות)\n")

            for i in range(60):
                await asyncio.sleep(1)
                if await self._is_logged_in_check():
                    print(f"\n✅ התחברות הצליחה! (אחרי {i+1} שניות)")
                    self.is_logged_in = True
                    await self.human_delay(2, 3)
                    return True

                if (i + 1) % 10 == 0:
                    print(f"   ... עדיין ממתין ({60-i-1} שניות נותרו)")

            print("\n❌ פג זמן ההתחברות - נסה שוב")
            return False

        except Exception as e:
            print(f"❌ שגיאה בהתחברות: {e}")
            self.db.log_error("login_error", str(e), "התחברות לפייסבוק")
            return False
    
    async def scan_group(self, group_info: Dict) -> List[Dict]:
        """
        סריקת קבוצה ספציפית
        
        Returns:
            list: רשימת פוסטים שנמצאו
        """
        group_name = group_info['name']
        group_url = group_info['url']
        
        if not group_url:
            print(f"⚠️ אין URL לקבוצה {group_name}")
            return []
        
        print(f"\n🔍 סורק קבוצה: {group_name}")
        
        try:
            # מעבר לקבוצה
            await self.page.goto(group_url, wait_until='domcontentloaded', timeout=60000)
            await self.human_delay(2, 3)

            # בדיקה שלא הועברנו לדף login
            current_url = self.page.url
            if 'login' in current_url.lower() or 'checkpoint' in current_url.lower():
                print(f"❌ הועברנו לדף התחברות - הסשן פג תוקף")
                return []
            
            # גלילה למטה כמה פעמים לטעינת פוסטים
            posts_to_scan = config.AUTOMATION_SETTINGS['posts_to_scan_per_group']
            print(f"📜 גולל למטה לטעינת {posts_to_scan} פוסטים...")
            for i in range(5):  # 5 גלילות מהירות
                await self.scroll_naturally()
                await self.human_delay(1, 2)
                print(f"   טעון פוסטים... ({i+1}/5 גלילות)")
            
            # צילום מסך דיבוג לפני חילוץ
            try:
                debug_dir = config.DATA_DIR / "screenshots"
                debug_dir.mkdir(exist_ok=True)
                debug_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                await self.page.screenshot(path=str(debug_dir / f"debug_group_{debug_ts}.png"))
            except:
                pass

            # חילוץ פוסטים
            posts = await self.extract_posts_from_page(group_name, posts_to_scan)
            
            print(f"✅ נמצאו {len(posts)} פוסטים בקבוצה")
            
            # עדכון סטטיסטיקות
            self.db.update_daily_stats(posts_scanned=len(posts))
            
            return posts
            
        except Exception as e:
            print(f"❌ שגיאה בסריקת קבוצה {group_name}: {e}")
            self.db.log_error("scan_error", str(e), f"סריקת קבוצה: {group_name}")
            self.db.update_daily_stats(errors=1)
            return []
    
    async def extract_posts_from_page(self, group_name: str, max_posts: int) -> List[Dict]:
        """חילוץ פוסטים מהעמוד הנוכחי"""
        posts = []
        
        try:
            # מציאת כל הפוסטים בעמוד
            post_elements = await self.page.locator('[role="article"]').all()
            print(f"   🔎 נמצאו {len(post_elements)} אלמנטי article בעמוד")

            # אם אין article, ננסה סלקטורים חלופיים
            if len(post_elements) == 0:
                alt_selectors = [
                    'div[data-ad-comet-preview="message"]',
                    'div.x1yztbdb',
                    'div[role="feed"] > div',
                ]
                for sel in alt_selectors:
                    post_elements = await self.page.locator(sel).all()
                    if len(post_elements) > 0:
                        print(f"   🔎 נמצאו {len(post_elements)} פוסטים עם סלקטור: {sel[:40]}")
                        break

            for i, post_element in enumerate(post_elements[:max_posts]):
                try:
                    # חילוץ טקסט הפוסט
                    post_text = await post_element.inner_text()
                    
                    # דילוג על פוסטים קצרים מדי
                    if len(post_text) < 10:
                        continue
                    
                    post_url = await self.extract_post_url(post_element)
                    posted_at = await self.extract_post_timestamp(post_element)

                    # יצירת ID יציב לפוסט (URL אם קיים, אחרת hash יציב)
                    post_id = self.build_post_id(group_name, post_text, post_url)
                    
                    # בדיקה אם כבר עיבדנו את הפוסט הזה
                    if self.db.is_post_processed(post_id):
                        continue
                    
                    # נסיון לחלץ שם מחבר (אופציונלי)
                    author_name = ""
                    try:
                        # נסיון מספר 1: חיפוש קישור עם התפקיד link
                        author_element = await post_element.locator('a[role="link"]').first.inner_text()
                        author_name = clean_author_name(author_element)
                    except:
                        try:
                            # נסיון מספר 2: השורה הראשונה בפוסט (לרוב השם)
                            first_line = post_text.split('\n')[0].strip()
                            author_name = clean_author_name(first_line)
                        except:
                            pass
                    
                    # יצירת אובייקט פוסט
                    post = {
                        'post_id': post_id,
                        'group_name': group_name,
                        'author_name': author_name,
                        'post_text': post_text,
                        'post_url': post_url or self.page.url,
                        'posted_at': posted_at,
                        'element': post_element  # שמירת האלמנט לשימוש מאוחר יותר
                    }
                    
                    posts.append(post)
                    
                except Exception as e:
                    print(f"⚠️ שגיאה בחילוץ פוסט #{i}: {e}")
                    continue
            
        except Exception as e:
            print(f"❌ שגיאה בחילוץ פוסטים: {e}")
        
        return posts
    
    async def process_and_respond_to_posts(self, posts: List[Dict]):
        """עיבוד והגבה לפוסטים"""
        candidates_found = 0
        responses_sent = 0
        
        for post in posts:
            try:
                # ניתוח הפוסט
                analysis = self.matcher.analyze_post(
                    post['post_text'],
                    post.get('author_name', ''),
                    post.get('posted_at')
                )
                
                # שמירה במסד נתונים
                post_data = {
                    **post,
                    'is_candidate': analysis['is_candidate'],
                    'candidate_score': analysis['candidate_score'],
                    'matched_keywords': analysis.get('matched_keywords', [])
                }
                self.db.add_scanned_post(post_data)
                
                # אם זה לא מועמד, ממשיכים הלאה
                if not analysis['is_candidate']:
                    continue
                
                candidates_found += 1
                print(f"\n✅ מצאנו מועמד! ציון: {analysis['candidate_score']:.1f}/10")
                print(f"   מחבר: {post.get('author_name', 'לא ידוע')}")
                print(f"   טקסט: {post['post_text'][:100]}...")
                
                # בדיקה אם צריך לענות
                if not analysis['should_respond']:
                    print(f"   ⏭️ לא עונים: {analysis['reason']}")
                    continue
                
                # בדיקת מגבלות יומיות
                daily_count = self.db.get_daily_response_count()
                max_daily = config.AUTOMATION_SETTINGS['max_responses_per_day']
                
                if daily_count >= max_daily:
                    print(f"   ⏸️ הגענו למגבלה היומית ({max_daily} תגובות)")
                    break
                
                # בדיקה אם כבר הגבנו לפוסט זה (מיד לפני תגובה)
                if self.db.has_responded_to_post(post['post_id']):
                    print("   ⏭️ Already responded")
                    continue
                
                # יצירת תגובה
                response = await self.create_and_send_response(post, analysis)
                
                if response:
                    responses_sent += 1
                    print("   ✅ תגובה נשלחה בהצלחה!")
                    
                    # עיכוב אקראי בין תגובות
                    delay = random.randint(
                        config.AUTOMATION_SETTINGS['delay_between_responses_min'],
                        config.AUTOMATION_SETTINGS['delay_between_responses_max']
                    )
                    print(f"   ⏳ ממתין {delay} שניות לפני התגובה הבאה...")
                    await asyncio.sleep(delay)
                    
            except Exception as e:
                print(f"❌ שגיאה בעיבוד פוסט: {e}")
                self.db.log_error("process_error", str(e), post.get('post_id', ''))
                continue
        
        # עדכון סטטיסטיקות
        self.db.update_daily_stats(
            candidates_found=candidates_found,
            responses_sent=responses_sent
        )
        
        print(f"\n📊 סיכום: {candidates_found} מועמדים, {responses_sent} תגובות נשלחו")
    
    async def create_and_send_response(self, post: Dict, analysis: Dict) -> bool:
        """יצירה ושליחת תגובה"""
        try:
            # בדיקה אחרונה לפני שליחה - למניעת תגובות כפולות
            if self.db.has_responded_to_post(post['post_id']):
                print("   ⏭️ Already responded")
                return False

            # יצירת התגובה
            candidate_info = analysis.get('candidate_info', {})
            matched_job = analysis.get('matched_job')

            if not matched_job:
                return False

            response_text = self.generator.generate_response(
                candidate_info,
                matched_job,
                post.get('author_name', '')
            )

            # הוספת נגיעה אישית
            response_text = self.generator.add_personal_touch(response_text, candidate_info)

            print(f"\n💬 תגובה שתישלח:")
            print(f"   {response_text}\n")

            # שליחת התגובה (אם יש element)
            if 'element' in post:
                # צילום מסך לפני הניסיון
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                screenshot_dir = config.DATA_DIR / "screenshots"
                screenshot_dir.mkdir(exist_ok=True)

                # ניקוי צילומי מסך ישנים (שומר עד 50)
                cleanup_old_screenshots(screenshot_dir, max_files=50)

                try:
                    screenshot_before = screenshot_dir / f"before_{timestamp}.png"
                    await post['element'].screenshot(path=str(screenshot_before))
                    print(f"   📸 צילום מסך נשמר: {screenshot_before.name}")
                except:
                    pass  # אם לא הצליח - לא נורא

                # גלילה לאלמנט כדי לוודא שהוא נראה
                try:
                    await post['element'].scroll_into_view_if_needed(timeout=5000)
                    await self.human_delay(0.5, 1)
                except:
                    pass

                # חיפוש תיבת תגובה
                comment_box = None
                successful_method = None

                print("   🔍 מחפש תיבת תגובה...")

                # כל וריאציות אפשריות של כפתור תגובה בעברית ואנגלית
                comment_btn_selector = (
                    'div[role="button"]:has(span:text("תגובה")), '
                    'div[role="button"]:has(span:text("השב")), '
                    'div[role="button"]:has(span:text("Comment")), '
                    'div[role="button"]:has(span:text("Reply")), '
                    'div[aria-label*="תגובה"], '
                    'div[aria-label*="Comment"], '
                    'div[aria-label*="Leave a comment"], '
                    'div[aria-label*="השב"]'
                )

                # שיטה 1: לחיצה על אזור ה-placeholder "כתיבת תגובה ציבורית..."
                # ואז חיפוש תיבת הטקסט שנפתחה
                try:
                    print("      ניסיון 1: לחיצה על placeholder תגובה")
                    await post['element'].scroll_into_view_if_needed(timeout=3000)
                    await self.human_delay(0.5, 1)

                    # חיפוש placeholder של תגובה - הטקסט "כתיבת תגובה ציבורית..."
                    placeholder_selectors = [
                        'div[aria-label*="כתיבת תגובה"], div[aria-label*="Write a comment"]',
                        'div[role="textbox"], span[data-lexical-text="true"]',
                        ':text("כתיבת תגובה")',
                    ]
                    clicked_placeholder = False
                    for sel in placeholder_selectors:
                        try:
                            ph = post['element'].locator(sel).first
                            if await ph.count() > 0:
                                await ph.click(timeout=3000)
                                clicked_placeholder = True
                                print(f"      ✅ נלחץ placeholder ({sel[:30]})")
                                await self.human_delay(1, 2)
                                break
                        except:
                            continue

                    if not clicked_placeholder:
                        # fallback: לחיצה על כפתור "תגובה"/"השב"
                        comment_btn = post['element'].locator(comment_btn_selector).first
                        if await comment_btn.count() > 0:
                            await comment_btn.click(timeout=3000)
                            clicked_placeholder = True
                            print("      ✅ נלחץ כפתור תגובה")
                            await self.human_delay(1, 2)

                    if clicked_placeholder:
                        # חיפוש תיבת טקסט פעילה - בעמוד כולו
                        textbox = self.page.locator(
                            'div[role="textbox"][contenteditable="true"], '
                            'div[contenteditable="true"][data-lexical-editor="true"], '
                            'div[contenteditable="true"][aria-label*="תגובה"], '
                            'div[contenteditable="true"][aria-label*="comment" i]'
                        ).first
                        try:
                            await textbox.wait_for(state='visible', timeout=5000)
                            await textbox.click(timeout=3000)
                            comment_box = textbox
                            successful_method = "placeholder click + page textbox"
                            print(f"   ✅ תיבת תגובה נמצאה! (שיטה: {successful_method})")
                        except:
                            # נסה contenteditable כללי
                            textbox = self.page.locator('div[contenteditable="true"]').last
                            if await textbox.count() > 0:
                                await textbox.click(timeout=3000)
                                comment_box = textbox
                                successful_method = "placeholder + last editable"
                                print(f"   ✅ תיבת תגובה נמצאה! (שיטה: {successful_method})")
                            else:
                                print("      ⚠️ נלחץ אבל תיבת טקסט לא נמצאה")
                    else:
                        print("      ❌ לא נמצא placeholder או כפתור תגובה")
                except Exception as e:
                    print(f"      ❌ נכשל: {str(e)[:80]}")

                # שיטה 2: חיפוש תיבת טקסט קיימת בעמוד כולו
                if not successful_method:
                    try:
                        print("      ניסיון 2: חיפוש תיבת טקסט פעילה בעמוד")
                        textbox = self.page.locator('div[contenteditable="true"]').last
                        if await textbox.count() > 0:
                            await textbox.scroll_into_view_if_needed(timeout=2000)
                            await textbox.click(timeout=3000)
                            comment_box = textbox
                            successful_method = "page-wide editable"
                            print(f"   ✅ תיבת תגובה נמצאה! (שיטה: {successful_method})")
                        else:
                            print("      ❌ לא נמצאה תיבת טקסט בעמוד")
                    except Exception as e:
                        print(f"      ❌ נכשל: {str(e)[:80]}")

                # שיטה 3: ניווט לעמוד הפוסט וחיפוש שם
                if not successful_method:
                    try:
                        post_url = post.get('post_url')
                        if post_url and 'facebook.com' in post_url:
                            print(f"      ניסיון 3: ניווט לעמוד הפוסט")
                            await self.page.goto(post_url, wait_until='domcontentloaded', timeout=30000)
                            await self.human_delay(3, 5)

                            # נסה ללחוץ על כפתור תגובה
                            comment_btn = self.page.locator(comment_btn_selector).first
                            if await comment_btn.count() > 0:
                                await comment_btn.click(timeout=3000)
                                await self.human_delay(1, 2)

                            # חיפוש תיבת טקסט
                            textbox = self.page.locator(
                                'div[role="textbox"][contenteditable="true"], '
                                'div[contenteditable="true"][data-lexical-editor="true"], '
                                'div[contenteditable="true"]'
                            ).first
                            await textbox.wait_for(state='visible', timeout=8000)
                            await textbox.click(timeout=3000)
                            comment_box = textbox
                            successful_method = "post page"
                            print(f"   ✅ תיבת תגובה נמצאה! (שיטה: {successful_method})")
                        else:
                            print("      ❌ אין URL לפוסט")
                    except Exception as e:
                        print(f"      ❌ נכשל: {str(e)[:80]}")

                if not comment_box or not successful_method:
                    print("   ⚠️ לא נמצאה תיבת תגובה, מדלג...")
                    try:
                        screenshot_failed = screenshot_dir / f"failed_{timestamp}.png"
                        await post['element'].screenshot(path=str(screenshot_failed))
                        print(f"   📸 צילום מסך כישלון: {screenshot_failed.name}")
                    except:
                        pass
                    return False

                # המתנה לוודא שתיבת התגובה מוכנה
                await self.human_delay(1, 2)

                # הקלדה אנושית
                print("   ⌨️ מקליד את התגובה...")
                await self.human_type(comment_box, response_text)
                await self.human_delay(1, 1.5)

                # שליחת התגובה - Enter שולח תגובה בפייסבוק
                print("   📤 שולח תגובה...")
                await comment_box.press('Enter')
                await self.human_delay(3, 4)

                # צילום מסך אחרי שליחה
                try:
                    screenshot_after = screenshot_dir / f"after_{timestamp}.png"
                    await post['element'].screenshot(path=str(screenshot_after))
                    print(f"   📸 צילום מסך אחרי שליחה: {screenshot_after.name}")
                except:
                    pass

                # שמירת התגובה במסד הנתונים
                response_data = {
                    'post_id': post['post_id'],
                    'response_text': response_text,
                    'matched_job': matched_job['job_key'],
                    'match_score': matched_job['match_score'],
                    'status': 'sent'
                }
                self.db.add_response(response_data)

                return True

        except Exception as e:
            print(f"❌ שגיאה בשליחת תגובה: {e}")
            self.db.log_error("response_error", str(e), post.get('post_id', ''))

            # צילום מסך של שגיאה
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                screenshot_dir = config.DATA_DIR / "screenshots"
                screenshot_dir.mkdir(exist_ok=True)
                screenshot_error = screenshot_dir / f"error_{timestamp}.png"
                if 'element' in post:
                    await post['element'].screenshot(path=str(screenshot_error))
                    print(f"   📸 צילום מסך של שגיאה: {screenshot_error.name}")
            except:
                pass

            return False
    
    def build_post_id(self, group_name: str, post_text: str, post_url: Optional[str]) -> str:
        """יצירת מזהה יציב לפוסט"""
        if post_url:
            return post_url.split("?", 1)[0]

        payload = f"{group_name}|{post_text}".encode("utf-8")
        stable_hash = hashlib.sha256(payload).hexdigest()[:16]
        return f"{group_name}_{stable_hash}"

    async def extract_post_url(self, post_element) -> Optional[str]:
        """חילוץ URL של פוסט מתוך האלמנט"""
        try:
            link_candidates = post_element.locator(
                'a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid="]'
            )
            if await link_candidates.count() > 0:
                href = await link_candidates.first.get_attribute("href")
                if href:
                    return href
        except Exception:
            pass
        return None

    async def extract_post_timestamp(self, post_element) -> Optional[str]:
        """חילוץ זמן פרסום של הפוסט"""
        try:
            utime_el = post_element.locator('abbr[data-utime], span[data-utime]')
            if await utime_el.count() > 0:
                utime = await utime_el.first.get_attribute("data-utime")
                if utime and utime.isdigit():
                    return datetime.fromtimestamp(int(utime)).isoformat()
        except Exception:
            pass

        try:
            time_el = post_element.locator('time[datetime]')
            if await time_el.count() > 0:
                datetime_str = await time_el.first.get_attribute("datetime")
                if datetime_str:
                    return datetime_str
        except Exception:
            pass

        return None

    async def human_delay(self, min_sec: float, max_sec: float):
        """עיכוב אקראי שנראה אנושי"""
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)
    
    async def human_type(self, element, text: str):
        """הקלדה שנראית אנושית עם מהירות משתנה"""
        for char in text:
            # בפייסבוק Enter שולח תגובה - נשתמש ב-Shift+Enter לשבירת שורה
            if char == '\n':
                await element.press('Shift+Enter')
                await asyncio.sleep(random.uniform(0.2, 0.5))
                continue

            await element.type(char, delay=random.randint(50, 150))

            # סיכוי קטן לטעות ותיקון
            if random.random() < 0.03:  # 3% סיכוי
                # הקלדת תו שגוי
                wrong_char = random.choice('abcdefghijklmnopqrstuvwxyz')
                await element.type(wrong_char, delay=random.randint(50, 100))
                await asyncio.sleep(0.2)
                # תיקון - backspace
                await element.press('Backspace')
                await asyncio.sleep(0.1)

            # פעם בפעם - השהיית חשיבה
            if random.random() < 0.10:  # 10% סיכוי
                await asyncio.sleep(random.uniform(0.3, 1.0))
    
    async def scroll_naturally(self):
        """גלילה שנראית טבעית"""
        # גלילה בקטעים קטנים עם תנועת עכבר
        for _ in range(random.randint(2, 4)):
            scroll_amount = random.randint(300, 600)
            await self.page.evaluate(f'window.scrollBy(0, {scroll_amount})')
            await asyncio.sleep(random.uniform(0.3, 0.8))
    
    async def close(self):
        """סגירת הדפדפן וניקוי כל המשאבים"""
        try:
            if self.context:
                await self.context.close()
                self.context = None
                self.page = None
                print("✅ דפדפן נסגר (הסשן נשמר)")
        except Exception as e:
            print(f"⚠️ שגיאה בסגירת הדפדפן: {e}")
        finally:
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None


# פונקציה ראשית להרצה
async def run_scan_session():
    """הרצת סשן סריקה אחד"""
    scraper = FacebookScraper()
    
    try:
        # הפעלה והתחברות
        await scraper.start()
        
        if not await scraper.login_to_facebook():
            print("❌ לא הצלחנו להתחבר לפייסבוק")
            return
        
        # סריקת כל הקבוצות - עיבוד פוסטים בכל קבוצה מיד
        # (אלמנטים הופכים ללא תקפים אחרי ניווט לעמוד אחר)
        total_candidates = 0
        total_responses = 0
        groups_with_url = [g for g in config.TARGET_GROUPS if g.get('url')]
        skipped = len(config.TARGET_GROUPS) - len(groups_with_url)
        if skipped:
            print(f"⚠️ דילוג על {skipped} קבוצות ללא URL")

        for idx, group_info in enumerate(groups_with_url):
            posts = await scraper.scan_group(group_info)

            # עיבוד פוסטים מיד בזמן שאנחנו עדיין בעמוד הקבוצה
            if posts:
                await scraper.process_and_respond_to_posts(posts)

            # עיכוב בין קבוצות (לא אחרי הקבוצה האחרונה)
            if idx < len(groups_with_url) - 1:
                delay = random.randint(
                    config.AUTOMATION_SETTINGS['delay_between_groups_min'],
                    config.AUTOMATION_SETTINGS['delay_between_groups_max']
                )
                print(f"⏳ ממתין {delay} שניות לפני הקבוצה הבאה...")
                await asyncio.sleep(delay)
        
    except Exception as e:
        print(f"❌ שגיאה כללית: {e}")
        scraper.db.log_error("general_error", str(e), "run_scan_session")
    
    finally:
        await scraper.close()


if __name__ == "__main__":
    # בדיקה מהירה
    print("🚀 מפעיל בוט גיוס AIG...\n")
    asyncio.run(run_scan_session())
