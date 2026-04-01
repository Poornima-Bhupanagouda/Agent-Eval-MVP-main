"""
Context generator for Lilly Agent Eval.

Generates sample context documents based on agent domain/purpose.
"""

import random
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class GeneratedContext:
    """Generated sample context for testing."""
    domain: str
    samples: List[str]
    source: str = "generated"


class ContextGenerator:
    """
    Generate sample context based on agent domain/purpose.

    Uses domain-specific templates with realistic placeholder values.
    """

    # Domain-specific context templates
    DOMAIN_TEMPLATES = {
        "hr_policies": [
            "Full-time employees receive {pto_days} days of paid time off (PTO) annually.",
            "Remote work is allowed up to {remote_days} days per week with manager approval.",
            "Mileage reimbursement rate is ${mileage_rate} per mile for business travel.",
            "Health insurance coverage begins on the first day of employment.",
            "401(k) matching is provided up to {match_percent}% of employee contributions.",
            "Annual performance reviews occur in {review_month}.",
            "Parental leave provides {parental_weeks} weeks of paid leave for new parents.",
            "Educational assistance covers up to ${edu_amount} per year for approved courses.",
            "Employees must complete {training_hours} hours of compliance training annually.",
            "Time off requests require {notice_days} business days advance notice.",
        ],
        "customer_support": [
            "Product returns are accepted within {return_days} days of purchase with receipt.",
            "Shipping is free for orders over ${free_ship_amount}.",
            "Warranty coverage extends for {warranty_months} months from purchase date.",
            "Customer service hours are {service_hours}.",
            "Refunds are processed within {refund_days} business days.",
            "Premium members receive {discount_percent}% discount on all purchases.",
            "Order tracking is available within {tracking_hours} hours of shipment.",
            "Gift cards do not expire and can be used on any purchase.",
            "Price matching is available for identical items within {price_match_days} days.",
            "Exchanges can be made at any store location or online.",
        ],
        "healthcare": [
            "Take {medication} {dosage} with food, {frequency} daily.",
            "Side effects may include {side_effects}.",
            "Follow up with your doctor in {followup_weeks} weeks.",
            "Do not operate heavy machinery while taking this medication.",
            "Store medication at room temperature away from moisture.",
            "Take the full course of antibiotics even if you feel better.",
            "Blood pressure should be monitored {bp_frequency}.",
            "Drink at least {water_glasses} glasses of water daily.",
            "Avoid {avoid_foods} while on this treatment.",
            "Emergency symptoms include {emergency_symptoms}.",
        ],
        "finance": [
            "Account balance is ${balance} as of {date}.",
            "Interest rate for savings accounts is {interest_rate}%.",
            "Minimum payment due is ${min_payment} by {due_date}.",
            "Wire transfer fee is ${wire_fee} for domestic transfers.",
            "ATM withdrawals are free at {atm_network} locations.",
            "Overdraft protection covers up to ${overdraft_limit}.",
            "Monthly account fee is waived with direct deposit over ${dd_minimum}.",
            "Foreign transaction fee is {foreign_fee}%.",
            "Credit limit increase requests can be submitted every {credit_months} months.",
            "Fraud alerts are sent via {alert_method} for unusual activity.",
        ],
        "legal": [
            "Contract term is {contract_months} months from effective date.",
            "Termination requires {termination_days} days written notice.",
            "Confidentiality obligations survive for {confidential_years} years after termination.",
            "Disputes shall be resolved through {dispute_method}.",
            "Governing law is the state of {governing_state}.",
            "Liability is limited to ${liability_cap}.",
            "Assignment requires prior written consent of all parties.",
            "Force majeure events excuse performance obligations.",
            "Amendments must be in writing and signed by both parties.",
            "Notices shall be sent to the addresses listed in Exhibit A.",
        ],
        "technical": [
            "API rate limit is {rate_limit} requests per minute.",
            "Authentication token expires after {token_expiry} hours.",
            "Maximum payload size is {max_payload}MB.",
            "Supported formats are {formats}.",
            "Response time SLA is {sla_ms}ms for 99th percentile.",
            "Retry with exponential backoff after {retry_codes} errors.",
            "SDK is available for {languages}.",
            "Webhook events are signed with {signing_algo}.",
            "Deprecated endpoints will be removed after {deprecation_months} months notice.",
            "Connection timeout is {timeout_seconds} seconds.",
        ],
        "general": [
            "Our service is available {availability}.",
            "Contact support at {support_email}.",
            "Updates are released {release_frequency}.",
            "Documentation is available at {docs_url}.",
            "The system supports {supported_languages} languages.",
            "Data is backed up {backup_frequency}.",
            "Security audits are conducted {audit_frequency}.",
            "New features are announced in our {announcement_channel}.",
            "Service level agreement guarantees {uptime}% uptime.",
            "Training resources are available at {training_url}.",
        ],
    }

    # Placeholder values for each domain
    PLACEHOLDER_VALUES = {
        "hr_policies": {
            "pto_days": ["15", "20", "25"],
            "remote_days": ["2", "3", "4"],
            "mileage_rate": ["0.65", "0.67", "0.70"],
            "match_percent": ["3", "4", "6"],
            "review_month": ["January", "March", "September"],
            "parental_weeks": ["8", "12", "16"],
            "edu_amount": ["5000", "7500", "10000"],
            "training_hours": ["8", "16", "24"],
            "notice_days": ["5", "10", "14"],
        },
        "customer_support": {
            "return_days": ["30", "60", "90"],
            "free_ship_amount": ["35", "50", "75"],
            "warranty_months": ["12", "24", "36"],
            "service_hours": ["9 AM - 5 PM EST", "24/7", "8 AM - 8 PM EST"],
            "refund_days": ["3", "5", "7"],
            "discount_percent": ["10", "15", "20"],
            "tracking_hours": ["12", "24", "48"],
            "price_match_days": ["7", "14", "30"],
        },
        "healthcare": {
            "medication": ["Lisinopril", "Metformin", "Atorvastatin"],
            "dosage": ["10mg", "20mg", "500mg"],
            "frequency": ["once", "twice", "three times"],
            "side_effects": ["drowsiness, dry mouth", "nausea, headache", "dizziness, fatigue"],
            "followup_weeks": ["2", "4", "6"],
            "bp_frequency": ["daily", "twice weekly", "weekly"],
            "water_glasses": ["6", "8", "10"],
            "avoid_foods": ["grapefruit", "alcohol", "high-sodium foods"],
            "emergency_symptoms": ["chest pain, difficulty breathing", "severe headache, vision changes", "high fever, confusion"],
        },
        "finance": {
            "balance": ["1,234.56", "5,678.90", "12,345.67"],
            "date": ["March 1, 2026", "today", "end of last month"],
            "interest_rate": ["0.5", "1.5", "3.0"],
            "min_payment": ["25", "50", "100"],
            "due_date": ["the 15th", "the 1st", "the last day of the month"],
            "wire_fee": ["25", "30", "35"],
            "atm_network": ["AllPoint", "MoneyPass", "any"],
            "overdraft_limit": ["100", "250", "500"],
            "dd_minimum": ["500", "1000", "2500"],
            "foreign_fee": ["1", "2", "3"],
            "credit_months": ["3", "6", "12"],
            "alert_method": ["SMS", "email", "push notification"],
        },
        "legal": {
            "contract_months": ["12", "24", "36"],
            "termination_days": ["30", "60", "90"],
            "confidential_years": ["2", "3", "5"],
            "dispute_method": ["arbitration", "mediation", "litigation"],
            "governing_state": ["Delaware", "California", "New York"],
            "liability_cap": ["100,000", "500,000", "1,000,000"],
        },
        "technical": {
            "rate_limit": ["100", "1000", "10000"],
            "token_expiry": ["1", "24", "168"],
            "max_payload": ["5", "10", "25"],
            "formats": ["JSON, XML", "JSON", "JSON, CSV, XML"],
            "sla_ms": ["100", "200", "500"],
            "retry_codes": ["429, 503", "5xx", "429"],
            "languages": ["Python, JavaScript, Go", "Python, Java, Node.js", "all major languages"],
            "signing_algo": ["HMAC-SHA256", "RSA-SHA256", "Ed25519"],
            "deprecation_months": ["6", "12", "18"],
            "timeout_seconds": ["30", "60", "120"],
        },
        "general": {
            "availability": ["24/7", "Monday-Friday 9-5", "business hours"],
            "support_email": ["support@example.com", "help@company.com", "contact@service.io"],
            "release_frequency": ["weekly", "monthly", "quarterly"],
            "docs_url": ["docs.example.com", "help.company.com", "developer.service.io"],
            "supported_languages": ["10+", "25+", "English and Spanish"],
            "backup_frequency": ["hourly", "daily", "continuously"],
            "audit_frequency": ["annually", "quarterly", "bi-annually"],
            "announcement_channel": ["newsletter", "blog", "changelog"],
            "uptime": ["99.9", "99.99", "99.5"],
            "training_url": ["learn.example.com", "academy.company.com", "training.service.io"],
        },
    }

    def generate(
        self,
        domain: str,
        purpose: Optional[str] = None,
        count: int = 5
    ) -> GeneratedContext:
        """
        Generate sample context for a given domain.

        Args:
            domain: The domain to generate context for
            purpose: Optional agent purpose for context refinement
            count: Number of context samples to generate

        Returns:
            GeneratedContext with sample documents
        """
        # Normalize domain
        domain = self._normalize_domain(domain, purpose)

        # Get templates for domain
        templates = self.DOMAIN_TEMPLATES.get(domain, self.DOMAIN_TEMPLATES["general"])
        placeholders = self.PLACEHOLDER_VALUES.get(domain, self.PLACEHOLDER_VALUES["general"])

        # Select and fill templates
        selected_templates = random.sample(templates, min(count, len(templates)))
        samples = []

        for template in selected_templates:
            sample = self._fill_template(template, placeholders)
            samples.append(sample)

        return GeneratedContext(
            domain=domain,
            samples=samples,
            source="generated",
        )

    def generate_for_domain(self, domain: str, count: int = 5) -> GeneratedContext:
        """Convenience method matching API signature."""
        return self.generate(domain=domain, count=count)

    def _normalize_domain(self, domain: str, purpose: Optional[str] = None) -> str:
        """Normalize domain string to known domain."""
        domain_lower = domain.lower().replace(" ", "_").replace("-", "_")

        # Direct match
        if domain_lower in self.DOMAIN_TEMPLATES:
            return domain_lower

        # Try to infer from purpose
        if purpose:
            purpose_lower = purpose.lower()
            for known_domain, templates in self.DOMAIN_TEMPLATES.items():
                # Check if domain keywords appear in purpose
                if known_domain.replace("_", " ") in purpose_lower:
                    return known_domain

        # Map common variations
        domain_aliases = {
            "hr": "hr_policies",
            "human_resources": "hr_policies",
            "policies": "hr_policies",
            "support": "customer_support",
            "customer": "customer_support",
            "help_desk": "customer_support",
            "medical": "healthcare",
            "health": "healthcare",
            "clinical": "healthcare",
            "banking": "finance",
            "financial": "finance",
            "money": "finance",
            "contracts": "legal",
            "compliance": "legal",
            "api": "technical",
            "developer": "technical",
            "engineering": "technical",
        }

        return domain_aliases.get(domain_lower, "general")

    def _fill_template(self, template: str, placeholders: dict) -> str:
        """Fill template placeholders with random values."""
        result = template

        for key, values in placeholders.items():
            placeholder = "{" + key + "}"
            if placeholder in result:
                result = result.replace(placeholder, random.choice(values))

        return result

    def get_available_domains(self) -> List[str]:
        """Return list of available domains."""
        return list(self.DOMAIN_TEMPLATES.keys())
