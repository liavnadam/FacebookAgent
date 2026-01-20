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
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.is_logged_in = False
    
    async def start(self):
        """הפעלת הדפדפן והתחברות"""
        playwright = await async_playwright().start()

        # נתיב לשמירת הסשן
        user_data_dir = config.DATA_DIR / "browser_session"
        user_data_dir.mkdir(exist_ok=True)

        print(f"💾 משתמש בסשן שמור: {user_data_dir}")

        # בחירת User Agent אקראי לכל הפעלה (stealth)
        user_agent = config.get_random_user_agent()
        print(f"🕵️ User Agent: {user_agent[:50]}...")

        # פתיחת דפדפן עם persistent context (שומר cookies וסשן)
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=config.BROWSER_SETTINGS['headless'],
            slow_mo=config.BROWSER_SETTINGS['slow_mo'],
            viewport=config.BROWSER_SETTINGS['viewport'],
            user_agent=user_agent,
            args=["--start-maximized"]
        )

        self.browser = context.browser
        self.page = context.pages[0] if context.pages else await context.new_page()

        # החלת טכניקות הסוואה
        stealth = Stealth()
        await stealth.apply_stealth_async(self.page)

        print("✅ דפדפן הופעל בהצלחה")
    
    async def login_to_facebook(self):
        """התחברות לפייסבוק"""
        try:
            print("🔐 בודק התחברות לפייסבוק...")

            # מעבר לפייסבוק (domcontentloaded מהיר יותר מ-networkidle)
            await self.page.goto('https://www.facebook.com/', wait_until='domcontentloaded', timeout=60000)
            await self.human_delay(3, 5)

            # בדיקה אם כבר מחוברים - חיפוש סימנים שונים
            print("🔍 בודק אם כבר מחובר...")

            # אם אנחנו בדף הבית של פייסבוק (לא בדף login), כנראה שמחוברים
            current_url = self.page.url
            if 'login' not in current_url.lower() and 'facebook.com' in current_url:
                print("✅ כבר מחובר לפייסבוק!")
                self.is_logged_in = True
                return True
            
            # אם לא מחוברים - מציע התחברות ידנית
            print("\n" + "="*60)
            print("⚠️  לא מחובר לפייסבוק!")
            print("="*60)
            print("\n📝 אפשרויות:")
            print("   1. התחבר ידנית בחלון הדפדפן שנפתח")
            print("   2. המתן 60 שניות לביצוע התחברות")
            print("   3. הבוט ימשיך אוטומטית לאחר ההתחברות\n")
            print("⏳ ממתין להתחברות ידנית...")
            print("   (יש לך 60 שניות להתחבר)\n")

            # ממתין עד 60 שניות שהמשתמש יתחבר ידנית
            for i in range(60):
                await asyncio.sleep(1)
                current_url = self.page.url

                # בדיקה אם המשתמש התחבר
                if 'login' not in current_url.lower():
                    print(f"\n✅ התחברות הצליחה! (אחרי {i+1} שניות)")
                    self.is_logged_in = True
                    await self.human_delay(2, 3)
                    return True

                # הדפסת נקודות התקדמות
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
            # מעבר לקבוצה (domcontentloaded מהיר ויציב יותר)
            await self.page.goto(group_url, wait_until='domcontentloaded', timeout=60000)
            await self.human_delay(2, 3)  # זמן קצר לטעינת הפוסטים
            
            # גלילה למטה כמה פעמים לטעינת פוסטים
            posts_to_scan = config.AUTOMATION_SETTINGS['posts_to_scan_per_group']
            print(f"📜 גולל למטה לטעינת {posts_to_scan} פוסטים...")
            for i in range(5):  # 5 גלילות מהירות
                await self.scroll_naturally()
                await self.human_delay(1, 2)
                print(f"   טעון פוסטים... ({i+1}/5 גלילות)")
            
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
            # שים לב: הסלקטורים של פייסבוק משתנים - אלו הם גנריים
            post_elements = await self.page.locator('[role="article"]').all()
            
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

                # אסטרטגיה חדשה: חיפוש של כל תיבות טקסט עריכה בפוסט
                comment_box = None
                successful_method = None

                print("   🔍 מחפש תיבת תגובה...")

                # שיטה 0: שימוש ב-Relative Locators - מצא Like ואז Comment ליד
                try:
                    print("      ניסיון 0: חיפוש כפתור תגובה ליד כפתור לייק (Relative Locator)")
                    # מצא את אזור הכפתורים (Like, Comment, Share) וחפש את הלייק
                    action_bar = post['element'].locator('div[role="button"]')
                    buttons = await action_bar.all()

                    for button in buttons:
                        try:
                            button_text = await button.inner_text()
                            # אם זה כפתור לייק, הכפתור הבא הוא כנראה תגובה
                            if any(word in button_text.lower() for word in ['like', 'לייק', 'אהבתי']):
                                comment_button = button.locator('xpath=following-sibling::div[@role="button"][1]')
                                if await comment_button.count() > 0:
                                    await comment_button.first.click(timeout=2000)
                                    print("      ✅ נלחץ על כפתור תגובה (אחרי לייק)")
                                    await self.human_delay(1, 1.5)
                                    break
                        except:
                            continue
                except Exception as e:
                    print(f"      ⚠️ שיטת Relative Locator נכשלה: {str(e)[:40]}")

                # שיטה 0b: נסה למצוא אזור תגובות ישירות
                try:
                    comment_area_selectors = [
                        'div[aria-label*="תגובה"]',
                        'div[aria-label*="Comment"]',
                        'span:has-text("תגובה"):not(:has-text("תגובות"))',
                        'div[aria-label*="Write"]',
                        'div[aria-label*="כתוב"]',
                    ]
                    for selector in comment_area_selectors:
                        try:
                            element = post['element'].locator(selector).first
                            if await element.count() > 0:
                                await element.click(timeout=2000)
                                print(f"      ✅ נלחץ על: {selector[:30]}")
                                await self.human_delay(1, 1.5)
                                break
                        except:
                            continue
                except Exception as e:
                    print(f"      ⚠️ שגיאה בלחיצה: {str(e)[:50]}")

                # שיטה 1: חפש תיבת טקסט עריכה בתוך הפוסט (contenteditable)
                try:
                    print(f"      ניסיון 1: חיפוש div[contenteditable=true] בפוסט")
                    editables_list = await post['element'].locator('div[contenteditable="true"]').all()

                    if len(editables_list) > 0:
                        print(f"      נמצאו {len(editables_list)} אלמנטים עריכים")
                        comment_box = editables_list[0]
                        await comment_box.scroll_into_view_if_needed(timeout=2000)
                        await comment_box.click(timeout=3000)
                        successful_method = f"contenteditable (1/{len(editables_list)})"
                        print(f"   ✅ תיבת תגובה נמצאה! (שיטה: {successful_method})")
                    else:
                        print("      ❌ לא נמצאו אלמנטים עריכים בפוסט")
                except Exception as e:
                    print(f"      ❌ נכשל: {str(e)[:80]}")

                # שיטה 2: חפש תיבת תגובה בכל העמוד (אחרי לחיצה על כפתור תגובה)
                if not successful_method:
                    try:
                        print(f"      ניסיון 2: חיפוש תיבת תגובה פעילה בעמוד")
                        # חפש תיבת טקסט עם placeholder של תגובה
                        comment_box = self.page.locator('div[contenteditable="true"][aria-placeholder*="תגובה"], div[contenteditable="true"][aria-placeholder*="comment"], div[role="textbox"][aria-label*="תגובה"], div[role="textbox"][aria-label*="comment"]').first
                        await comment_box.wait_for(state='visible', timeout=3000)
                        await comment_box.click(timeout=3000)
                        successful_method = "page-wide comment box"
                        print(f"   ✅ תיבת תגובה נמצאה! (שיטה: {successful_method})")
                    except Exception as e:
                        print(f"      ❌ נכשל: {str(e)[:80]}")

                # שיטה 3: חפש לפי role="textbox" בפוסט
                if not successful_method:
                    try:
                        print(f"      ניסיון 3: חיפוש div[role=textbox] בפוסט")
                        comment_box = post['element'].locator('div[role="textbox"]').first
                        await comment_box.scroll_into_view_if_needed(timeout=2000)
                        await comment_box.wait_for(state='visible', timeout=2000)
                        await comment_box.click(timeout=3000)
                        successful_method = "role=textbox"
                        print(f"   ✅ תיבת תגובה נמצאה! (שיטה: {successful_method})")
                    except Exception as e:
                        print(f"      ❌ נכשל: {str(e)[:80]}")

                # שיטה 4: נווט לעמוד הפוסט ותגיב שם
                if not successful_method:
                    try:
                        print(f"      ניסיון 4: ניווט לעמוד הפוסט")
                        post_url = post.get('post_url')
                        if post_url and 'facebook.com' in post_url:
                            await self.page.goto(post_url, wait_until='domcontentloaded', timeout=30000)
                            await self.human_delay(2, 3)

                            # חפש תיבת תגובה בעמוד הפוסט
                            comment_box = self.page.locator('div[contenteditable="true"][aria-label*="תגובה"], div[contenteditable="true"][aria-label*="comment"], div[role="textbox"][data-lexical-editor="true"]').first
                            await comment_box.wait_for(state='visible', timeout=5000)
                            await comment_box.click(timeout=3000)
                            successful_method = "post page comment box"
                            print(f"   ✅ תיבת תגובה נמצאה! (שיטה: {successful_method})")
                        else:
                            print("      ❌ אין URL לפוסט")
                    except Exception as e:
                        print(f"      ❌ נכשל: {str(e)[:80]}")

                if not comment_box or not successful_method:
                    print("   ⚠️ לא נמצאה תיבת תגובה בכל השיטות, מדלג...")
                    # צילום מסך כשנכשל
                    try:
                        screenshot_failed = screenshot_dir / f"failed_{timestamp}.png"
                        await post['element'].screenshot(path=str(screenshot_failed))
                        print(f"   📸 צילום מסך של כישלון נשמר: {screenshot_failed.name}")
                    except:
                        pass
                    return False

                # המתנה לוודא שתיבת התגובה מוכנה
                await self.human_delay(1, 2)

                # הקלדה אנושית
                print("   ⌨️ מקליד את התגובה...")
                await self.human_type(comment_box, response_text)
                await self.human_delay(1, 1.5)

                # שליחת התגובה - כפתור שליחה (לא Enter)
                print("   📤 שולח תגובה...")
                send_success = False

                # נסה למצוא כפתור שליחה (אייקון חץ/מטוס נייר)
                try:
                    send_button_selectors = [
                        'div[aria-label*="שלח"]',
                        'div[aria-label*="Send"]',
                        'button[aria-label*="Send"]',
                        'button[type="submit"]',
                        'div[aria-label*="submit"]',
                        'div[aria-label*="Post"]',
                        'div[aria-label*="פרסם"]',
                        'div[role="button"][tabindex="0"]:near(div[contenteditable="true"])',
                    ]
                    for selector in send_button_selectors:
                        try:
                            send_btn = self.page.locator(selector).first
                            if await send_btn.count() > 0:
                                await send_btn.click(timeout=3000)
                                send_success = True
                                print("      ✅ נלחץ על כפתור שליחה")
                                break
                        except:
                            continue
                except Exception as e:
                    print(f"      ⚠️ לא נמצא כפתור שליחה: {str(e)[:30]}")

                if not send_success:
                    print("      ❌ לא נמצא כפתור שליחה, מדלג על תגובה")
                    return False

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
        """סגירת הדפדפן"""
        if self.page:
            await self.page.context.close()
            print("✅ דפדפן נסגר (הסשן נשמר)")


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
        
        # סריקת כל הקבוצות
        all_posts = []
        for group_info in config.TARGET_GROUPS:
            if not group_info.get('url'):
                print(f"⚠️ דלג על קבוצה {group_info['name']} - אין URL")
                continue
            
            posts = await scraper.scan_group(group_info)
            all_posts.extend(posts)
            
            # עיכוב בין קבוצות
            delay = random.randint(
                config.AUTOMATION_SETTINGS['delay_between_groups_min'],
                config.AUTOMATION_SETTINGS['delay_between_groups_max']
            )
            print(f"⏳ ממתין {delay} שניות לפני הקבוצה הבאה...")
            await asyncio.sleep(delay)
        
        # עיבוד והגבה לכל הפוסטים
        if all_posts:
            await scraper.process_and_respond_to_posts(all_posts)
        else:
            print("⚠️ לא נמצאו פוסטים לעיבוד")
        
    except Exception as e:
        print(f"❌ שגיאה כללית: {e}")
        scraper.db.log_error("general_error", str(e), "run_scan_session")
    
    finally:
        await scraper.close()


if __name__ == "__main__":
    # בדיקה מהירה
    print("🚀 מפעיל בוט גיוס AIG...\n")
    asyncio.run(run_scan_session())
