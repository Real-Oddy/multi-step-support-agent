# Project 5: Multi-Step Order Support Agent (Capstone)

## 📌 Project Overview
This is your final capstone project! You will synthesize everything you have learned (structured output schemas, deterministic business overrides, tool integrations, databases, and document retrieval) into a unified, production-grade **Multi-Step Order Support Agent**.

The agent acts as a customer support assistant. When a user asks an order-related question (e.g., "Where is my order?", "Can I cancel it?", "Why is it delayed?"), the agent must extract the relevant identifiers, invoke database queries or delivery APIs, apply complex corporate logic, retrieve policies if necessary, and output a structured response or escalate to a human.

---

## 🎯 Learning Objectives
By completing this project, you will learn:
1.  **Multi-Tool Execution Flows:** Orchestrating agents that call multiple sequential tools in a single execution loop.
2.  **State Management & Multi-Source Data:** Combining data queried from relational SQL databases with facts retrieved from a knowledge base (RAG).
3.  **Observability & Diagnostics:** Logging agent decision traces (which tools were called in what order and with what parameters).
4.  **Complex Business Workflows:** Writing conditional rules checking order stages, return periods, shipping statuses, and customer priority levels.
5.  **Graceful Escalation Chains:** Structuring the agent to write a support ticket to the DB automatically if manual intervention is required.

---

## ⚙️ Requirements & Technical Specifications

### 1. The Output Schema Fields
Your agent must respond to the customer using a structured model containing:
*   **order_number** (str): The relevant order identifier extracted from the conversation (or a fallback if none).
*   **current_status** (str): A short summary of the current status of the order (e.g., 'Shipped', 'Pending Payment', 'Cancelled').
*   **explanation** (str): A polite, natural language explanation detailing what was found (e.g., including transit info, policies, etc.).
*   **recommended_action** (str): Actionable next step for the customer or support team.
*   **escalation_required** (bool): Flag indicating if a support ticket was created, or if human intervention is required.

### 2. Mock Databases & API Integrations
You must build and populate:
*   **Database Tables (SQLite):**
    *   `orders`: Contains order number, customer ID, payment status (Pending/Paid), order status (Processing/Shipped/Delivered), waybill number, and timestamps.
    *   `support_tickets`: Tracks tickets created by the agent with fields for ticket ID, order number, reason, status, and creation timestamps.
*   **Mock Logistics/Delivery API Function:**
    *   A function to retrieve cargo tracking events, location updates, and estimated delivery dates using a waybill number.
*   **Return Policy Knowledge (RAG):**
    *   Integrate document retrieval from Project 4 to fetch return policies by category (e.g., "Electronics", "Clothing").

### 3. Concrete Business Rules to Enforce
Your agent or tool pipeline must execute the following rules:
*   **Cancellation Check:** An order can **only** be cancelled if its database status is `Processing` and payment status is `Pending`. If a user asks to cancel a shipped or paid order, explain the policy and set `escalation_required=True`.
*   **Delay Policy:** If the delivery status shows the arrival is delayed by more than 3 days past the estimated delivery date, automatically call the tool to create a support ticket, notify the customer, and set `escalation_required=True`.
*   **Ticket Creation:** If the agent cannot satisfy the request, it must run a tool to register a ticket in the database before returning the final response.

---

## 💡 Multi-Step Workflow Example
When a user asks: *"Where is my order ORD-1234? Can I cancel it?"*
1.  **Step 1:** The Agent calls a tool to get order details which returns status `Shipped` and waybill `WB-987`.
2.  **Step 2:** The Agent calls a tracking tool using the waybill number to check delivery status.
3.  **Step 3:** The Agent applies business rules: Since the status is `Shipped`, it cannot be cancelled.
4.  **Step 4:** The Agent compiles the findings and returns the structured response explaining where it is, stating cancellation is unavailable, and detailing next steps.
