"""
מנוע התאמת מועמדים למשרות
מזהה מועמדים פוטנציאליים ומתאים אותם למשרות פתוחות
"""

import re
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import config


class CandidateMatcher:
    """מזהה ומתאים מועמדים למשרות"""
    
    def __init__(self):
        self.positive_keywords = config.CANDIDATE_KEYWORDS['positive']
        self.negative_keywords = config.CANDIDATE_KEYWORDS['negative']
        self.open_positions = config.OPEN_POSITIONS
    
    def is_candidate_post(self, post_text: str) -> Tuple[bool, float, List[str]]:
        """
        בדיקה האם פוסט הוא של מועמד מחפש עבודה
        
        Returns:
            tuple: (האם מועמד, ציון, מילות מפתח שנמצאו)
        """
        if not post_text:
            return False, 0.0, []
        
        post_text_lower = post_text.lower()
        
        # בדיקת מילות מפתח שליליות (מעסיק מחפש עובדים)
        for negative_keyword in self.negative_keywords:
            if negative_keyword in post_text_lower:
                return False, 0.0, []
        
        # בדיקת מילות מפתח חיוביות (מועמד מחפש עבודה)
        matched_keywords = []
        for positive_keyword in self.positive_keywords:
            if positive_keyword in post_text_lower:
                matched_keywords.append(positive_keyword)
        
        # חישוב ציון
        if len(matched_keywords) == 0:
            return False, 0.0, []
        
        # ציון מ-0 עד 10
        score = min(len(matched_keywords) * 3.0, 10.0)
        
        # בונוס אם הפוסט קצר (סביר שזה מחפש עבודה ולא משהו אחר)
        if len(post_text) < 200:
            score += 1.0
        
        # בונוס אם יש התייחסות למיקום
        locations = ["פתח תקווה", "הוד השרון", "כפר סבא", "רעננה", "המרכז", "השרון"]
        for location in locations:
            if location in post_text:
                score += 0.5
        
        score = min(score, 10.0)  # מקסימום 10
        
        is_candidate = score >= 3.0  # סף של 3.0
        
        return is_candidate, score, matched_keywords
    
    def match_to_job(self, post_text: str, _author_name: str = "") -> Optional[Dict]:
        """
        התאמת מועמד למשרה מתאימה
        
        Returns:
            dict: פרטי המשרה המתאימה ביותר או None אם אין התאמה
        """
        post_text_lower = post_text.lower()
        best_match = None
        best_score = 0.0
        
        for job_key, job_info in self.open_positions.items():
            match_score = 0.0
            matched_requirements = []
            
            # התאמה לפי מילות מפתח של המשרה
            for keyword in job_info['keywords']:
                if keyword in post_text_lower:
                    match_score += 2.0
                    matched_requirements.append(keyword)
            
            # בדיקת מיקום
            for location in job_info['locations']:
                if location in post_text:
                    match_score += 1.5
                    break
            
            # אם יש התאמה טובה, שמור אותה
            if match_score > best_score:
                best_score = match_score
                best_match = {
                    "job_key": job_key,
                    "job_info": job_info,
                    "match_score": match_score,
                    "matched_keywords": matched_requirements
                }
        
        # החזרת המשרה הכי טובה אם יש ציון מספיק
        if best_match and best_match['match_score'] >= 1.5:
            return best_match
        
        # אם אין התאמה ספציפית, נחזיר את המשרה הכללית ביותר
        # (סוכן ביטוח - הכי כללי)
        default_job = self.open_positions.get("סוכן ביטוח")
        if default_job:
            return {
                "job_key": "סוכן ביטוח",
                "job_info": default_job,
                "match_score": 2.0,  # ציון בסיסי
                "matched_keywords": []
            }
        
        return None
    
    def extract_candidate_info(self, post_text: str, author_name: str = "") -> Dict:
        """
        חילוץ מידע על המועמד מהפוסט
        
        Returns:
            dict: מידע על המועמד
        """
        info = {
            "name": author_name,
            "has_phone": False,
            "has_experience": False,
            "locations_mentioned": [],
            "skills_mentioned": []
        }
        
        # חיפוש מספר טלפון
        phone_pattern = r'0\d{1,2}[-\s]?\d{7}'
        if re.search(phone_pattern, post_text):
            info['has_phone'] = True
        
        # חיפוש ניסיון
        experience_keywords = ["ניסיון", "עבדתי", "התנסות", "שנים", "שנות"]
        for keyword in experience_keywords:
            if keyword in post_text.lower():
                info['has_experience'] = True
                break
        
        # מיקומים
        locations = ["פתח תקווה", "הוד השרון", "כפר סבא", "רעננה", "המרכז", "השרון", "תל אביב"]
        for location in locations:
            if location in post_text:
                info['locations_mentioned'].append(location)
        
        # מיומנויות רלוונטיות
        skills = ["מכירות", "שירות", "ביטוח", "לקוחות", "מחשב", "משרד", "טלפון"]
        for skill in skills:
            if skill in post_text.lower():
                info['skills_mentioned'].append(skill)
        
        return info
    
    def should_respond(self, post_data: Dict) -> Tuple[bool, str]:
        """
        החלטה אם לענות לפוסט
        
        Returns:
            tuple: (האם לענות, סיבה)
        """
        # בדיקת גיל הפוסט
        if 'posted_at' in post_data:
            try:
                posted_date = datetime.fromisoformat(post_data['posted_at'])
                max_age = timedelta(days=config.AUTOMATION_SETTINGS['max_post_age_days'])
                
                if datetime.now() - posted_date > max_age:
                    return False, "הפוסט ישן מדי"
            except:
                pass  # אם יש שגיאה בפרסור התאריך, נמשיך
        
        # בדיקת ציון מועמד
        if post_data.get('candidate_score', 0) < 3.0:
            return False, "ציון מועמד נמוך מדי"
        
        # בדיקה אם יש התאמה למשרה
        if not post_data.get('matched_job'):
            return False, "אין התאמה למשרה"
        
        return True, "מתאים למענה"
    
    def analyze_post(self, post_text: str, author_name: str = "", 
                    posted_at: str = None) -> Dict:
        """
        ניתוח מקיף של פוסט
        
        Returns:
            dict: כל המידע המנותח על הפוסט
        """
        # בדיקה אם זה מועמד
        is_candidate, candidate_score, matched_keywords = self.is_candidate_post(post_text)
        
        result = {
            "is_candidate": is_candidate,
            "candidate_score": candidate_score,
            "matched_keywords": matched_keywords,
            "candidate_info": None,
            "matched_job": None,
            "should_respond": False,
            "reason": ""
        }
        
        if not is_candidate:
            result['reason'] = "לא זוהה כמועמד"
            return result
        
        # חילוץ מידע על המועמד
        result['candidate_info'] = self.extract_candidate_info(post_text, author_name)
        
        # התאמה למשרה
        job_match = self.match_to_job(post_text, author_name)
        if job_match:
            result['matched_job'] = job_match
        
        # החלטה אם לענות
        post_data = {
            'candidate_score': candidate_score,
            'matched_job': job_match,
            'posted_at': posted_at
        }
        should_respond, reason = self.should_respond(post_data)
        result['should_respond'] = should_respond
        result['reason'] = reason
        
        return result


# פונקציות עזר
def get_matcher() -> CandidateMatcher:
    """קבלת instance של מנוע ההתאמה"""
    return CandidateMatcher()


if __name__ == "__main__":
    # בדיקה של המנוע
    matcher = CandidateMatcher()
    
    # דוגמאות לבדיקה
    test_posts = [
        {
            "text": "היי, אני מחפש עבודה באזור פתח תקווה. יש לי ניסיון במכירות ושירות לקוחות.",
            "author": "דני כהן"
        },
        {
            "text": "דרושים מיידי! חברתנו מחפשת עובדים למכירות",
            "author": "חברת XYZ"
        },
        {
            "text": "מעוניינת במשרה בתחום השירות, אני גרה בהוד השרון",
            "author": "מיכל לוי"
        }
    ]
    
    print("🔍 בדיקת מנוע ההתאמה:\n")
    for i, post in enumerate(test_posts, 1):
        print(f"--- פוסט #{i} ---")
        print(f"טקסט: {post['text']}")
        print(f"מחבר: {post['author']}")
        
        analysis = matcher.analyze_post(post['text'], post['author'])
        
        print(f"האם מועמד: {'✅ כן' if analysis['is_candidate'] else '❌ לא'}")
        print(f"ציון: {analysis['candidate_score']:.1f}/10")
        
        if analysis['matched_job']:
            print(f"משרה מתאימה: {analysis['matched_job']['job_info']['title']}")
            print(f"ציון התאמה: {analysis['matched_job']['match_score']:.1f}")
        
        print(f"לענות: {'✅ כן' if analysis['should_respond'] else '❌ לא'}")
        print(f"סיבה: {analysis['reason']}\n")