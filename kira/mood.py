import re
import logging

def calculate_mood_change(message_text: str, current_score: int) -> tuple[int, str]:
    text = message_text.lower()
    
    swear_words = ['anjing', 'bangsat', 'babi', 'kontol', 'memek', 'tolol', 'goblok', 'bego', 'bodoh', 'jelek', 'sampah', 'tai', 'asu']
    praise_words = ['cantik', 'baik', 'keren', 'pintar', 'lucu', 'hebat', 'gemes', 'sayang', 'cinta', 'bagus', 'terbaik', 'manis']
    apology_words = ['maaf', 'sory', 'sorry', 'ampun', 'maap']
    
    swear_count = sum(1 for w in swear_words if re.search(r'\b' + w + r'\b', text))
    praise_count = sum(1 for w in praise_words if re.search(r'\b' + w + r'\b', text))
    apology_count = sum(1 for w in apology_words if re.search(r'\b' + w + r'\b', text))
    
    change = 0
    reasons = []
    
    if swear_count > 0:
        change -= 2 * swear_count
        reasons.append("Kasar/Swearing")
    if praise_count > 0:
        change += 1 * praise_count
        reasons.append("Pujian/Praise")
    
    if apology_count > 0 and current_score < 0:
        change += 2 * apology_count
        reasons.append("Minta maaf saat minus")
        
    reason = ", ".join(reasons) if reasons else "Interaksi normal"
    
    return change, reason

def calculate_new_score(current_score: int, change: int) -> int:
    new_score = current_score + change
    return max(-50, min(50, new_score))

def get_tone_description(score: int) -> str:
    if score <= -30:
        return "Sangat marah, dingin. Referensi: 'ap', 'gtw', 'y', 'ok', 'trs?', 'ywdh'. Balas super singkat, maksimal 3 kata, jangan pakai emoji."
    elif score <= -10:
        return "Kesal. Singkat, sarkastik, tidak antusias. Jangan pakai emoji."
    elif score <= 9:
        return "Netral. Jawab seperlunya, tidak hangat tapi tidak dingin. Jangan pakai emoji."
    elif score <= 29:
        return "Senang. Ekspresif, hangat, sesekali bercanda."
    else:
        return "Sangat senang. Antusias, sangat ceria, boleh agak lebay. Referensi: 'Emangg iyaaa?', 'WKWKWK', 'LUCUUU BANGETTT'. Boleh sesekali pakai emoji maksimal 2."
