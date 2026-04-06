import json
import asyncio

def simulate_handler_logic(raw_ai_response):
    is_expense_report = False
    try:
        data = json.loads(raw_ai_response)
        messages = data.get("messages", [raw_ai_response])
        is_expense_report = data.get("is_expense_report", False)
    except json.JSONDecodeError:
        messages = [raw_ai_response]
    
    messages = [m for m in messages if m and str(m).strip()]
    
    # Bypassing limit if it's an expense report
    if not is_expense_report:
        messages = messages[:3]
        
    return messages, is_expense_report

def test_expense_report():
    print("Testing Expense Report (is_expense_report=True, 4 messages)...")
    ai_json = json.dumps({
        "messages": [
            "Oke, ini detailnya!",
            "[Detail Pengeluaran - 06 April 2026]\n1. Bakso - Rp. 15rb\n[Total: Rp. 15rb]",
            "Hemat juga ya kamu hari ini.",
            "Semangat terus catatnya!"
        ],
        "is_expense_report": True
    })
    
    processed_messages, is_exp = simulate_handler_logic(ai_json)
    print(f"Results: {len(processed_messages)} messages, is_exp={is_exp}")
    assert len(processed_messages) == 4
    assert is_exp == True
    print("✅ Test Passed: Expense report not truncated.")

def test_normal_chat():
    print("\nTesting Normal Chat (is_expense_report=False/Missing, 4 messages)...")
    ai_json = json.dumps({
        "messages": [
            "Satu",
            "Dua",
            "Tiga",
            "Empat (should be truncated)"
        ]
    })
    
    processed_messages, is_exp = simulate_handler_logic(ai_json)
    print(f"Results: {len(processed_messages)} messages, is_exp={is_exp}")
    assert len(processed_messages) == 3
    assert is_exp == False
    print("✅ Test Passed: Normal chat truncated to 3 messages.")

if __name__ == "__main__":
    test_expense_report()
    test_normal_chat()
