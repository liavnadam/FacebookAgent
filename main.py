"""
קובץ ראשי להפעלת בוט גיוס AIG
מריץ סשני סריקה לפי לוח זמנים מוגדר
Production Ready - עם מנגנון retry והתאוששות משגיאות
"""

import asyncio
import sys
import shutil
import argparse
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import config
from facebookScraper import run_scan_session
from database import get_db


# הגדרות Retry
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 30


async def run_with_retry(func, *args, **kwargs):
    """
    הרצת פונקציה עם מנגנון retry לשגיאות רשת

    Args:
        func: הפונקציה להרצה
        *args, **kwargs: פרמטרים לפונקציה

    Returns:
        תוצאת הפונקציה או None אם כל הניסיונות נכשלו
    """
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await func(*args, **kwargs)
        except (ConnectionError, TimeoutError, OSError) as e:
            last_error = e
            if attempt < MAX_RETRIES:
                print(f"⚠️ שגיאת רשת (ניסיון {attempt}/{MAX_RETRIES}): {str(e)[:50]}")
                print(f"   ממתין {RETRY_DELAY_SECONDS} שניות לפני ניסיון נוסף...")
                await asyncio.sleep(RETRY_DELAY_SECONDS)
            else:
                print(f"❌ כל {MAX_RETRIES} הניסיונות נכשלו")
                raise last_error
        except Exception as e:
            # שגיאות אחרות - לא מנסים שוב
            print(f"❌ שגיאה לא צפויה: {e}")
            raise

    return None


def is_active_time() -> bool:
    """
    בדיקה אם זה זמן פעיל לסריקה
    
    Returns:
        bool: האם זה זמן מתאים לסריקה
    """
    now = datetime.now()
    
    # בדיקת יום בשבוע
    if now.weekday() not in config.AUTOMATION_SETTINGS['active_days']:
        return False
    
    # בדיקת שעה
    hour = now.hour
    if not (config.AUTOMATION_SETTINGS['active_hours_start'] <= 
            hour < config.AUTOMATION_SETTINGS['active_hours_end']):
        return False
    
    return True


async def scheduled_scan():
    """פונקציה שמופעלת בכל תזמון"""
    print(f"\n{'='*60}")
    print(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    
    # בדיקה אם זה זמן פעיל
    if not is_active_time():
        print("⏸️ לא בזמן פעיל - מדלג על סריקה")
        return
    
    # בדיקת מגבלה יומית
    db = get_db()
    daily_responses = db.get_daily_response_count()
    max_daily = config.AUTOMATION_SETTINGS['max_responses_per_day']
    
    if daily_responses >= max_daily:
        print(f"⏸️ הגענו למגבלה היומית ({max_daily} תגובות)")
        print(f"   תגובות היום: {daily_responses}/{max_daily}")
        return
    
    print(f"📊 תגובות היום עד כה: {daily_responses}/{max_daily}")
    print("\n🚀 מתחיל סשן סריקה...\n")
    
    try:
        await run_with_retry(run_scan_session)
        print("\n✅ סשן סריקה הושלם בהצלחה\n")
    except Exception as e:
        print(f"\n❌ שגיאה בסשן סריקה: {e}\n")
        db.log_error("scheduler_error", str(e), "scheduled_scan")


async def run_once():
    """הרצה חד פעמית לבדיקה"""
    print("🔧 מצב בדיקה - הרצה אחת\n")
    await scheduled_scan()


async def run_scheduler():
    """הפעלת תזמון רציף"""
    print("=" * 60)
    print(" 🤖 בוט גיוס AIG - מצב תזמון אוטומטי")
    print("=" * 60)
    print(f"\n📅 ימי פעילות: {config.AUTOMATION_SETTINGS['active_days']}")
    print(f"🕐 שעות פעילות: {config.AUTOMATION_SETTINGS['active_hours_start']:02d}:00 - {config.AUTOMATION_SETTINGS['active_hours_end']:02d}:00")
    print(f"📊 מגבלה יומית: {config.AUTOMATION_SETTINGS['max_responses_per_day']} תגובות")
    print(f"\n💾 מסד נתונים: {config.DATABASE_FILE}")
    print(f"📝 לוגים: {config.LOG_FILE}")
    print("\n" + "=" * 60 + "\n")
    
    # יצירת scheduler
    scheduler = AsyncIOScheduler()

    active_days = config.AUTOMATION_SETTINGS.get('active_days', [])
    day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    if active_days:
        day_of_week = ",".join(day_names[day] for day in active_days if 0 <= day <= 6)
    else:
        day_of_week = "mon-sun"

    start_hour = config.AUTOMATION_SETTINGS.get('active_hours_start', 0)
    end_hour = config.AUTOMATION_SETTINGS.get('active_hours_end', 24)
    if end_hour <= start_hour:
        hour_expr = "0-23/2"
    else:
        last_hour = min(end_hour - 1, 23)
        hour_expr = f"{start_hour}-{last_hour}/2"
    
    # תזמון - כל 2 שעות בימים פעילים
    scheduler.add_job(
        scheduled_scan,
        CronTrigger(
            hour=hour_expr,  # כל 2 שעות בחלון הפעילות
            day_of_week=day_of_week
        ),
        id='facebook_scan',
        max_instances=1,  # מונע חפיפה
        replace_existing=True
    )
    
    # הפעלת scheduler
    scheduler.start()
    print("✅ תזמון הופעל!")
    print("⏰ סריקה אוטומטית כל 2 שעות בין 9:00-20:00, א'-ה'")
    print("\n💡 לחץ Ctrl+C לעצירה\n")
    
    try:
        # שמירה על הפרוגרמה פעילה
        while True:
            await asyncio.sleep(3600)  # שעה
    except (KeyboardInterrupt, SystemExit):
        print("\n\n⏹️ עוצר את הבוט...")
        scheduler.shutdown()
        print("✅ הבוט נעצר בהצלחה")


def show_statistics(days: int = 7):
    """הצגת סטטיסטיקות"""
    db = get_db()
    stats = db.get_statistics(days)
    
    print("\n" + "=" * 60)
    print(f" 📊 סטטיסטיקות ל-{days} ימים אחרונים")
    print("=" * 60 + "\n")
    
    print(f"📄 פוסטים שנסרקו:        {stats['total_posts_scanned']}")
    print(f"👤 מועמדים שנמצאו:        {stats['total_candidates_found']}")
    print(f"💬 תגובות ששלחנו:         {stats['total_responses_sent']}")
    print(f"❌ שגיאות:                {stats['total_errors']}")
    print(f"\n📈 שיעור המרה:            {stats['conversion_rate']}%")
    
    if stats['total_candidates_found'] > 0:
        response_rate = (stats['total_responses_sent'] / stats['total_candidates_found']) * 100
        print(f"📊 שיעור תגובה למועמדים: {response_rate:.1f}%")
    
    print("\n" + "=" * 60 + "\n")


def setup_environment():
    """וידוא שהסביבה מוגדרת נכון"""
    # בדיקת משתני סביבה
    if not config.FACEBOOK_CREDENTIALS['email'] or not config.FACEBOOK_CREDENTIALS['password']:
        print("❌ שגיאה: משתני הסביבה FB_EMAIL ו-FB_PASSWORD לא מוגדרים!")
        print("\nאנא:")
        print("1. צור קובץ .env")
        print("2. הוסף:")
        print("   FB_EMAIL=your_email@example.com")
        print("   FB_PASSWORD=your_password")
        print("\n⚠️ זכור: השתמש בחשבון בדיקה, לא בחשבון האישי שלך!")
        sys.exit(1)
    
    # בדיקת URLs של קבוצות
    if not any(group.get('url') for group in config.TARGET_GROUPS):
        print("⚠️ אזהרה: לא הוגדרו URLs לקבוצות היעד!")
        print("\nערוך את config.py והוסף את הקישורים לקבוצות")
        print("דוגמה:")
        print('  {"name": "דרושים פתח תקווה", "url": "https://www.facebook.com/groups/...", "priority": 1}')
        print()
    
    # יצירת תיקיות
    config.DATA_DIR.mkdir(exist_ok=True)
    config.LOGS_DIR.mkdir(exist_ok=True)
    
    print("✅ הסביבה מוכנה\n")


def main():
    """נקודת כניסה ראשית"""
    parser = argparse.ArgumentParser(
        description='בוט גיוס עובדים ל-AIG - סריקת פייסבוק אוטומטית'
    )
    
    parser.add_argument(
        '--run-once',
        action='store_true',
        help='הרצה אחת בלבד (לבדיקה)'
    )
    
    parser.add_argument(
        '--stats',
        type=int,
        metavar='DAYS',
        nargs='?',
        const=7,
        help='הצג סטטיסטיקות (ברירת מחדל: 7 ימים)'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='מצב דיבוג'
    )

    parser.add_argument(
        '--reset-session',
        action='store_true',
        help='מחיקת סשן דפדפן ישן והתחברות מחדש'
    )

    args = parser.parse_args()

    # הצגת סטטיסטיקות
    if args.stats is not None:
        show_statistics(args.stats)
        return

    # איפוס סשן דפדפן
    if args.reset_session:
        session_dir = config.DATA_DIR / "browser_session"
        if session_dir.exists():
            shutil.rmtree(session_dir)
            print("✅ סשן ישן נמחק - תתבקש להתחבר מחדש בהרצה הבאה")
        else:
            print("ℹ️ אין סשן שמור למחוק")
        if not args.run_once:
            return
    
    # וידוא שהסביבה מוכנה
    setup_environment()
    
    # הרצה לפי הפרמטרים
    if args.run_once:
        asyncio.run(run_once())
    else:
        asyncio.run(run_scheduler())


if __name__ == "__main__":
    main()
