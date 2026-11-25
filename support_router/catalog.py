from dataclasses import dataclass


@dataclass(frozen=True)
class SupportTeam:
    id: str
    name: str
    description: str


TEAMS = (
    SupportTeam(
        "account_access",
        "Account Access",
        "Enat system login, password resets, locked accounts, KYC user roles, maker and checker access, and account permissions.",
    ),
    SupportTeam(
        "payments",
        "Payment Operations",
        "Transfers, deposits, missing payments, transaction status, and payment reconciliation.",
    ),
    SupportTeam(
        "cards",
        "Card Services",
        "Debit and credit cards, card delivery, declined card transactions, and card replacement.",
    ),
    SupportTeam(
        "billing",
        "Billing Support",
        "Invoices, charges, balances, fees, billing statements, and payment disputes.",
    ),
    SupportTeam(
        "loans",
        "Loan Services",
        "Loan applications, repayment schedules, loan balances, and credit decisions.",
    ),
    SupportTeam(
        "human_resources",
        "Human Resources (HR)",
        "Employee records and HR profile corrections, including branch or department transfers, position, grade, name, and employment details.",
    ),
    SupportTeam(
        "technical_support",
        "Technical Support",
        "Application errors, website problems, outages, device compatibility, and technical faults.",
    ),
)

TEAM_BY_ID = {team.id: team for team in TEAMS}
