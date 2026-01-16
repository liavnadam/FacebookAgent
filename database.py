"""
מנהל מסד נתונים לבוט גיוס AIG
שומר מידע על פוסטים שנסרקו, תגובות ששלחנו, וסטטיסטיקות
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict
import json
import config


class DatabaseManager:
    """מנהל את מסד הנתונים של הבוט"""
    
    def __init__(self, db_path: Path = config.DATABASE_FILE):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """יצירת הטבלאות במסד הנתונים"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # טבלת פוסטים שנסרקו
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scanned_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT UNIQUE NOT NULL,
                group_name TEXT NOT NULL,
                author_name TEXT,
                post_text TEXT,
                post_url TEXT,
                posted_at TEXT,
                scanned_at TEXT NOT NULL,
                is_candidate BOOLEAN DEFAULT 0,
                candidate_score REAL DEFAULT 0.0,
                matched_keywords TEXT
            )
        """)
        
        # טבלת תגובות ששלחנו
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT NOT NULL,
                response_text TEXT NOT NULL,
                matched_job TEXT,
                match_score REAL,
                sent_at TEXT NOT NULL,
                status TEXT DEFAULT 'sent',
                FOREIGN KEY (post_id) REFERENCES scanned_posts(post_id)
            )
        """)
        
        # טבלת סטטיסטיקות יומיות
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                posts_scanned INTEGER DEFAULT 0,
                candidates_found INTEGER DEFAULT 0,
                responses_sent INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0
            )
        """)
        
        # טבלת לוג שגיאות
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS error_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                error_type TEXT,
                error_message TEXT,
                context TEXT
            )
        """)
        
        conn.commit()
        conn.close()
    
    def add_scanned_post(self, post_data: Dict) -> bool:
        """הוספת פוסט שנסרק למסד הנתונים"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR IGNORE INTO scanned_posts 
                (post_id, group_name, author_name, post_text, post_url, 
                 posted_at, scanned_at, is_candidate, candidate_score, matched_keywords)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                post_data.get('post_id'),
                post_data.get('group_name'),
                post_data.get('author_name'),
                post_data.get('post_text'),
                post_data.get('post_url'),
                post_data.get('posted_at'),
                datetime.now().isoformat(),
                post_data.get('is_candidate', False),
                post_data.get('candidate_score', 0.0),
                json.dumps(post_data.get('matched_keywords', []))
            ))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"❌ שגיאה בהוספת פוסט למסד נתונים: {e}")
            return False
    
    def is_post_processed(self, post_id: str) -> bool:
        """בדיקה אם פוסט כבר עובד"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM scanned_posts WHERE post_id = ?", (post_id,))
        result = cursor.fetchone()
        
        conn.close()
        return result is not None
    
    def has_responded_to_post(self, post_id: str) -> bool:
        """בדיקה אם כבר הגבנו לפוסט זה"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM responses WHERE post_id = ?", (post_id,))
        result = cursor.fetchone()
        
        conn.close()
        return result is not None
    
    def add_response(self, response_data: Dict) -> bool:
        """הוספת תגובה ששלחנו"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO responses 
                (post_id, response_text, matched_job, match_score, sent_at, status)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                response_data.get('post_id'),
                response_data.get('response_text'),
                response_data.get('matched_job'),
                response_data.get('match_score'),
                datetime.now().isoformat(),
                response_data.get('status', 'sent')
            ))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"❌ שגיאה בהוספת תגובה למסד נתונים: {e}")
            return False
    
    def get_daily_response_count(self, date: str = None) -> int:
        """קבלת מספר התגובות שנשלחו היום"""
        if date is None:
            date = datetime.now().date().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT COUNT(*) FROM responses 
            WHERE DATE(sent_at) = ?
        """, (date,))
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count
    
    def update_daily_stats(self, posts_scanned: int = 0, candidates_found: int = 0, 
                          responses_sent: int = 0, errors: int = 0):
        """עדכון סטטיסטיקות יומיות"""
        today = datetime.now().date().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO daily_stats (date, posts_scanned, candidates_found, responses_sent, errors)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                posts_scanned = posts_scanned + ?,
                candidates_found = candidates_found + ?,
                responses_sent = responses_sent + ?,
                errors = errors + ?
        """, (today, posts_scanned, candidates_found, responses_sent, errors,
              posts_scanned, candidates_found, responses_sent, errors))
        
        conn.commit()
        conn.close()
    
    def log_error(self, error_type: str, error_message: str, context: str = ""):
        """רישום שגיאה"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO error_log (timestamp, error_type, error_message, context)
            VALUES (?, ?, ?, ?)
        """, (datetime.now().isoformat(), error_type, error_message, context))
        
        conn.commit()
        conn.close()
    
    def get_statistics(self, days: int = 7) -> Dict:
        """קבלת סטטיסטיקות לימים האחרונים"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # סטטיסטיקות כלליות
        cursor.execute("""
            SELECT 
                SUM(posts_scanned) as total_posts,
                SUM(candidates_found) as total_candidates,
                SUM(responses_sent) as total_responses,
                SUM(errors) as total_errors
            FROM daily_stats
            WHERE date >= date('now', '-' || ? || ' days')
        """, (days,))
        
        stats = cursor.fetchone()
        
        result = {
            "period_days": days,
            "total_posts_scanned": stats[0] or 0,
            "total_candidates_found": stats[1] or 0,
            "total_responses_sent": stats[2] or 0,
            "total_errors": stats[3] or 0
        }
        
        # שיעור המרה
        if result["total_candidates_found"] > 0:
            result["conversion_rate"] = round(
                result["total_responses_sent"] / result["total_candidates_found"] * 100, 2
            )
        else:
            result["conversion_rate"] = 0
        
        conn.close()
        return result
    
    def cleanup_old_data(self, days: int = 30):
        """ניקוי נתונים ישנים"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # מחיקת פוסטים ישנים
        cursor.execute("""
            DELETE FROM scanned_posts 
            WHERE DATE(scanned_at) < date('now', '-' || ? || ' days')
        """, (days,))
        
        # מחיקת סטטיסטיקות ישנות
        cursor.execute("""
            DELETE FROM daily_stats 
            WHERE date < date('now', '-' || ? || ' days')
        """, (days,))
        
        conn.commit()
        conn.close()
        print(f"✅ נתונים מלפני {days} ימים נוקו מהמסד נתונים")


# פונקציות עזר
def get_db() -> DatabaseManager:
    """קבלת instance של מנהל מסד הנתונים"""
    return DatabaseManager()


if __name__ == "__main__":
    # בדיקה של מסד הנתונים
    db = DatabaseManager()
    print("✅ מסד הנתונים אותחל בהצלחה!")
    
    # הצגת סטטיסטיקות
    stats = db.get_statistics(7)
    print("\n📊 סטטיסטיקות ל-7 ימים אחרונים:")
    for key, value in stats.items():
        print(f"  {key}: {value}")