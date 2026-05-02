# Pricing (per 1 million tokens)
INPUT_COST_PER_M = 0.5
OUTPUT_COST_PER_M = 3.0

# Convert to per-token
IN_COST = INPUT_COST_PER_M / 1_000_000
OUT_COST = OUTPUT_COST_PER_M / 1_000_000

# Token usage data (added example 'thinking' tokens)
data = [
    {"stage": "OCR_questions", "input": 3545, "thinking": 0, "output": 1202},
    {"stage": "Rubric_generation", "input": 1666, "thinking": 450, "output": 3798},
    {"stage": "OCR_answers_1", "input": 6148, "thinking": 0, "output": 1342},
    {"stage": "Evaluation_1", "input": 3777, "thinking": 820, "output": 2430},
    # {"stage": "OCR_answers_2", "input": 5038, "thinking": 0, "output": 583},
    # {"stage": "Evaluation_2", "input": 2904, "thinking": 610, "output": 2056},
]

total_input_cost = 0
total_output_cost = 0

for item in data:
    in_cost = item["input"] * IN_COST
    
    # Thinking tokens and output tokens share the same price
    total_output_tokens = item["output"] + item.get("thinking", 0)
    out_cost = total_output_tokens * OUT_COST

    total_input_cost += in_cost
    total_output_cost += out_cost

    print(f"{item['stage']}:")
    print(f"  Input cost  : ${in_cost:.6f}")
    print(f"  Output cost : ${out_cost:.6f}")
    print(f"  Total cost  : ${in_cost + out_cost:.6f}\n")

# Final total
print("==== FINAL TOTAL ====")
print(f"Total Input Cost  : ${total_input_cost:.6f}")
print(f"Total Output Cost : ${total_output_cost:.6f}")
print(f"Grand Total       : ${total_input_cost + total_output_cost:.6f}")