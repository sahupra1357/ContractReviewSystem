"""Template families for the synthetic golden set (OQ-3: real estate).

Each family is the STANDARD text — Phase 5 template-diff treats it as the
baseline. Slots like {landlord} are filled by the generator. Planted issues
replace/remove specific sections and are recorded in labels.yaml.
"""

LEASE_V1 = {
    "family": "lease-v1",
    "title": "RESIDENTIAL LEASE AGREEMENT",
    "sections": [
        ("1. PARTIES",
         "This Lease Agreement is entered into on {effective_date} between "
         "{landlord} (\"Landlord\") and {tenant} (\"Tenant\"). Rent payments "
         "shall be made to account {account}."),
        ("2. PREMISES",
         "Landlord leases to Tenant the premises located at {address} "
         "(the \"Premises\"), for residential use only."),
        ("3. TERM",
         "The initial term of this Lease is {term_months} months, beginning "
         "on {effective_date}. This Lease renews automatically for successive "
         "12-month periods unless either party gives 60 days written notice."),
        ("4. RENT",
         "Tenant shall pay monthly rent of {monthly_amount}, due on the first "
         "day of each month. A late fee of 5% applies after a 5-day grace period."),
        ("5. SECURITY DEPOSIT",
         "Tenant shall deposit {deposit_amount} as security, refundable within "
         "30 days of lease end, less lawful deductions."),
        ("6. MAINTENANCE",
         "Tenant shall keep the Premises clean and promptly report damage. "
         "Landlord is responsible for structural repairs and building systems."),
        ("7. INSURANCE",
         "Tenant shall maintain renter's insurance with liability coverage of "
         "not less than 100,000 dollars for the duration of the term."),
        ("8. LIABILITY",
         "Landlord's aggregate liability under this Lease shall not exceed "
         "the total rent paid in the twelve months preceding any claim."),
        ("9. TERMINATION",
         "Either party may terminate for material breach with 30 days written "
         "notice and opportunity to cure."),
        ("10. GOVERNING LAW",
         "This Lease is governed by the laws of the State of {state}."),
        ("11. SIGNATURES",
         "Signed by {landlord_signer} for Landlord and {tenant} as Tenant on "
         "{effective_date}."),
    ],
}

PURCHASE_V1 = {
    "family": "purchase-v1",
    "title": "PROPERTY PURCHASE AGREEMENT",
    "sections": [
        ("1. PARTIES",
         "This Purchase Agreement is made on {effective_date} between {seller} "
         "(\"Seller\") and {buyer} (\"Buyer\")."),
        ("2. PROPERTY",
         "Seller agrees to sell the real property at {address}, together with "
         "all fixtures and improvements (the \"Property\")."),
        ("3. PURCHASE PRICE",
         "The total purchase price is {purchase_price}, payable at Closing by "
         "wire transfer to escrow account {account}."),
        ("4. EARNEST MONEY",
         "Buyer shall deposit {deposit_amount} as earnest money within 5 "
         "business days, refundable if any contingency in this Agreement fails."),
        ("5. CLOSING",
         "Closing shall occur on or before {closing_date} at a title company "
         "selected by mutual agreement."),
        ("6. TITLE",
         "Seller shall convey good and marketable title by general warranty "
         "deed, free of liens and encumbrances."),
        ("7. INSPECTION",
         "Buyer may inspect the Property within 10 days of acceptance and may "
         "terminate if material defects are found and not remedied."),
        ("8. DEFAULT",
         "If Buyer defaults, Seller's sole remedy is retention of the earnest "
         "money. If Seller defaults, Buyer may seek specific performance."),
        ("9. RISK OF LOSS",
         "Risk of loss remains with Seller until Closing."),
        ("10. GOVERNING LAW",
         "This Agreement is governed by the laws of the State of {state}."),
        ("11. SIGNATURES",
         "Signed by {seller_signer} for Seller and {buyer} as Buyer on "
         "{effective_date}."),
    ],
}

VENDOR_V1 = {
    "family": "vendor-services-v1",
    "title": "PROPERTY SERVICES AGREEMENT",
    "sections": [
        ("1. PARTIES",
         "This Services Agreement is made on {effective_date} between {owner} "
         "(\"Owner\") and {vendor} (\"Vendor\"). Invoices are payable to "
         "Vendor account {account}."),
        ("2. SERVICES",
         "Vendor shall provide {service_type} services for the property at "
         "{address}, per the schedule in Exhibit A."),
        ("3. TERM",
         "The term is {term_months} months from {effective_date}, renewable "
         "by written agreement of both parties."),
        ("4. COMPENSATION",
         "Owner shall pay {monthly_amount} per month, net 30 days from a "
         "correct invoice."),
        ("5. STANDARD OF WORK",
         "Vendor shall perform services in a professional and workmanlike "
         "manner consistent with industry standards."),
        ("6. INSURANCE",
         "Vendor shall maintain commercial general liability insurance of not "
         "less than 1,000,000 dollars per occurrence."),
        ("7. INDEMNIFICATION",
         "Vendor shall indemnify Owner against claims arising from Vendor's "
         "negligence or willful misconduct."),
        ("8. LIABILITY CAP",
         "Each party's aggregate liability shall not exceed the fees paid in "
         "the twelve months preceding the claim."),
        ("9. TERMINATION",
         "Either party may terminate with 30 days written notice; Owner may "
         "terminate immediately for uncured material breach."),
        ("10. GOVERNING LAW",
         "This Agreement is governed by the laws of the State of {state}."),
        ("11. SIGNATURES",
         "Signed by {owner_signer} for Owner and {vendor_signer} for Vendor "
         "on {effective_date}."),
    ],
}

FAMILIES = {t["family"]: t for t in (LEASE_V1, PURCHASE_V1, VENDOR_V1)}
