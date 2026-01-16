"""
מחולל תגובות לפוסטים של מועמדים
יוצר תגובות בעברית עם וריאציות שונות כדי להימנע מזיהוי
"""

import random
from typing import Dict
import config


class ResponseGenerator:
    """מייצר תגובות מותאמות אישית למועמדים"""
    
    def __init__(self):
        self.templates = config.RESPONSE_TEMPLATES
    
    def generate_response(self, candidate_info: Dict, matched_job: Dict, 
                         author_name: str = "") -> str:
        """
        יצירת תגובה מותאמת אישית
        
        Args:
            candidate_info: מידע על המועמד
            matched_job: המשרה שהותאמה
            author_name: שם המועמד
            
        Returns:
            str: התגובה המוכנה
        """
        # בחירת תבנית אקראית
        template = random.choice(self.templates)
        
        # הכנת המשתנים
        job_info = matched_job['job_info']
        name = self._format_name(author_name)
        job_title = job_info['title']
        location = self._choose_location(job_info['locations'], 
                                         candidate_info.get('locations_mentioned', []))
        requirements = self._format_requirements(job_info['requirements'])
        
        # מילוי התבנית
        response = template.format(
            name=name,
            job_title=job_title,
            location=location,
            requirements=requirements
        )
        
        return response
    
    def _format_name(self, name: str) -> str:
        """עיצוב השם בצורה יפה"""
        if not name:
            return "שם"
        
        # אם השם מכיל רק שם פרטי
        parts = name.split()
        if len(parts) == 1:
            return parts[0]
        
        # אם יש שם פרטי ומשפחה
        return parts[0]
    
    def _choose_location(self, job_locations: list, 
                        candidate_locations: list) -> str:
        """בחירת המיקום המתאים ביותר"""
        # אם המועמד ציין מיקום, נעדיף אותו
        for loc in candidate_locations:
            if loc in job_locations:
                return loc
        
        # אם המועמד ציין מיקום שלא במשרה, נציין "המרכז"
        if candidate_locations:
            return "המרכז"
        
        # אחרת, בחירה אקראית ממיקומי המשרה
        return random.choice(job_locations)
    
    def _format_requirements(self, requirements: list) -> str:
        """עיצוב הדרישות בצורה טבעית"""
        if not requirements:
            return "רצון להתפתח"
        
        # בחירת 1-2 דרישות אקראיות
        num_requirements = min(random.randint(1, 2), len(requirements))
        selected = random.sample(requirements, num_requirements)
        
        if len(selected) == 1:
            return selected[0]
        
        # חיבור עם "ו"
        return " ו".join(selected)
    
    def add_personal_touch(self, response: str, candidate_info: Dict) -> str:
        """הוספת נגיעה אישית לתגובה - מושבת לשמירה על טבעיות"""
        # לא מוסיפים כלום כדי שהתגובות יישארו קצרות וטבעיות
        # הוספות אוטומטיות גורמות לתגובות להישמע כמו בוט AI
        return response
    
    def create_variations(self, base_response: str, num_variations: int = 5) -> list:
        """יצירת וריאציות של אותה תגובה"""
        variations = [base_response]
        
        # החלפות אפשריות
        replacements = [
            ("היי", ["שלום", "שלום רב", "הי"]),
            ("מעניין אותך", ["תרצה לשמוע יותר", "תהיה מעוניין", "נשמע טוב"]),
            ("😊", ["🙂", "😃", "💼"]),
            ("אשמח", ["נשמח", "נ happy", "יש לנו"]),
            ("בפרטי", ["בהודעה פרטית", "במסרון", "בפרטי!"]),
        ]
        
        # יצירת וריאציות
        for _ in range(min(num_variations - 1, 4)):
            variant = base_response
            # בחירה אקראית של 1-2 החלפות
            num_replacements = random.randint(1, 2)
            selected_replacements = random.sample(replacements, 
                                                 min(num_replacements, len(replacements)))
            
            for original, options in selected_replacements:
                if original in variant:
                    variant = variant.replace(original, random.choice(options))
            
            if variant not in variations:
                variations.append(variant)
        
        return variations


# פונקציות עזר
def get_generator() -> ResponseGenerator:
    """קבלת instance של מחולל התגובות"""
    return ResponseGenerator()


if __name__ == "__main__":
    # בדיקה של המחולל
    generator = ResponseGenerator()
    
    # דוגמה
    candidate_info = {
        "name": "דני כהן",
        "has_experience": True,
        "skills_mentioned": ["מכירות", "שירות"],
        "locations_mentioned": ["פתח תקווה"]
    }
    
    matched_job = {
        "job_key": "סוכן ביטוח",
        "job_info": config.OPEN_POSITIONS["סוכן ביטוח"],
        "match_score": 7.5
    }
    
    print("🎨 בדיקת מחולל התגובות:\n")
    print("--- תגובה בסיסית ---")
    response = generator.generate_response(candidate_info, matched_job, "דני כהן")
    print(response)
    
    print("\n--- תגובה עם נגיעה אישית ---")
    response_personal = generator.add_personal_touch(response, candidate_info)
    print(response_personal)
    
    print("\n--- 3 וריאציות ---")
    variations = generator.create_variations(response, 3)
    for i, var in enumerate(variations, 1):
        print(f"\nווריאציה #{i}:")
        print(var)