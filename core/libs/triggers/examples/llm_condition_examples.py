"""Examples of LLM-based condition evaluation for triggers.

This module demonstrates how to use the LLM condition evaluator
for natural language trigger conditions.
"""

import json

# Example condition configurations

# Simple rule-based condition
RULE_CONDITION_EXAMPLE = {
    "type": "rule",
    "rules": [
        {"field": "request.method", "operator": "eq", "value": "POST"},
        {"field": "request.body.type", "operator": "eq", "value": "file"}
    ],
    "logic": "AND"
}

# LLM-based natural language condition
LLM_CONDITION_EXAMPLE = {
    "type": "llm",
    "description": "when user sends a file attachment or document",
    "context_fields": ["request.body", "request.headers"],
    "examples": [
        {
            "input": {
                "request": {
                    "body": {"document": {"file_name": "report.pdf"}},
                    "headers": {"content-type": "multipart/form-data"}
                }
            },
            "expected": True
        },
        {
            "input": {
                "request": {
                    "body": {"message": "Hello, how are you?"},
                    "headers": {"content-type": "application/json"}
                }
            },
            "expected": False
        }
    ]
}

# Combined condition with both rule and LLM evaluation
COMBINED_CONDITION_EXAMPLE = {
    "type": "combined",
    "conditions": [
        {
            "type": "rule",
            "rules": [{"field": "request.method", "operator": "eq", "value": "POST"}]
        },
        {
            "type": "llm",
            "description": "when the message looks like a sales inquiry or support request"
        }
    ],
    "logic": "AND"
}

# Example event data for testing
FILE_UPLOAD_EVENT = {
    "request": {
        "method": "POST",
        "headers": {
            "content-type": "multipart/form-data",
            "user-agent": "TelegramBot/1.0"
        },
        "body": {
            "document": {
                "file_name": "quarterly_report.pdf",
                "file_size": 1024000,
                "mime_type": "application/pdf"
            },
            "message": "Here's the quarterly report for review",
            "user": {
                "id": "123456",
                "name": "John Doe"
            }
        }
    },
    "timestamp": "2024-01-15T10:30:00Z"
}

TEXT_MESSAGE_EVENT = {
    "request": {
        "method": "POST",
        "headers": {
            "content-type": "application/json",
            "user-agent": "SlackBot/1.0"
        },
        "body": {
            "message": "Hello, I'm interested in your product pricing",
            "user": {
                "id": "789012",
                "name": "Jane Smith"
            },
            "channel": "sales-inquiries"
        }
    },
    "timestamp": "2024-01-15T10:35:00Z"
}

# Example task parameter extraction instructions
PARAMETER_EXTRACTION_EXAMPLES = {
    "file_analysis": "analyze the uploaded file and respond with insights about its content",
    "sales_inquiry": "extract customer information and their specific interests or questions",
    "support_request": "identify the issue type and extract relevant technical details"
}

def print_example(title: str, data: dict):
    """Print a formatted example."""
    print(f"\n{'='*60}")
    print(f"{title}")
    print(f"{'='*60}")
    print(json.dumps(data, indent=2))

def main():
    """Print all examples."""
    print("LLM Condition Evaluation Examples")
    print("=" * 60)

    print_example("1. Rule-Based Condition", RULE_CONDITION_EXAMPLE)
    print_example("2. LLM Natural Language Condition", LLM_CONDITION_EXAMPLE)
    print_example("3. Combined Condition", COMBINED_CONDITION_EXAMPLE)

    print_example("4. File Upload Event Data", FILE_UPLOAD_EVENT)
    print_example("5. Text Message Event Data", TEXT_MESSAGE_EVENT)

    print("\n" + "="*60)
    print("Parameter Extraction Instructions")
    print("="*60)
    for key, instruction in PARAMETER_EXTRACTION_EXAMPLES.items():
        print(f"{key}: {instruction}")

    print("\n" + "="*60)
    print("Usage Examples")
    print("="*60)
    print("""
# Example 1: File Upload Trigger
trigger = WebhookTrigger(
    name="Document Analysis Trigger",
    webhook_id="doc_analysis_webhook",
    conditions=LLM_CONDITION_EXAMPLE,
    task_parameters={
        "llm_parameter_extraction": "analyze the uploaded file and respond with insights"
    }
)

# Example 2: Sales Inquiry Router
trigger = WebhookTrigger(
    name="Sales Inquiry Router",
    webhook_id="sales_webhook",
    conditions={
        "type": "llm",
        "description": "when message looks like a sales inquiry or product question"
    },
    task_parameters={
        "llm_parameter_extraction": "extract customer information and their interests"
    }
)

# Example 3: Business Hours Cron Trigger
trigger = CronTrigger(
    name="Business Hours Report",
    cron_expression="0 9 * * 1-5",  # 9 AM on weekdays
    conditions={
        "type": "combined",
        "conditions": [
            {
                "type": "rule",
                "rules": [{"field": "time_conditions.weekdays_only", "operator": "eq", "value": True}]
            },
            {
                "type": "llm",
                "description": "during business hours on weekdays"
            }
        ],
        "logic": "AND"
    }
)
""")

if __name__ == "__main__":
    main()
