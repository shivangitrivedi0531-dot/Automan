"""
Trusted Schema & Business Context for ERP Sales AI Agent.

This module provides curated, authoritative metadata regarding PostgreSQL ERP Sales tables,
validated relationships, business rules, entity resolution sources, and safe query guidance.
"""

from typing import Dict, Any, List

SALES_TABLES: Dict[str, Dict[str, Any]] = {
    "public.transection": {
        "purpose": "Authoritative accounting transaction data for Sales (filter on inv_type = 'VSALE').",
        "population_status": "POPULATED",
        "is_authoritative_financial_source": True,
        "important_fields": [
            "inv_type", "inv_no", "doc_no", "from_doc_no", "doc_date",
            "series", "ev", "co_year", "ac_code", "debit", "credit",
            "amount", "vdate", "user_id", "auto_id"
        ],
        "description": "Primary accounting table containing all debits/credits and Sales financial totals."
    },
    "public.mst_history": {
        "purpose": "Vehicle master and Sales history information.",
        "population_status": "POPULATED",
        "is_authoritative_vehicle_source": True,
        "important_fields": [
            "hist_code", "chassis_no", "engine_no", "reg_no",
            "product_code", "sub_prd_code", "sale_date",
            "customer_name", "cust_code", "model", "series"
        ],
        "description": "Authoritative vehicle details and vehicle-to-product/customer history mapping."
    },
    "public.trn_jobcard": {
        "purpose": "Jobcard / invoice bridge connecting accounting invoices to vehicle history.",
        "population_status": "POPULATED",
        "important_fields": [
            "job_no", "job_date", "inv_type", "inv_no",
            "inv_dt", "service_no", "hist_code", "cust_code", "product_code"
        ],
        "description": "Bridge table linking transection.inv_no to mst_history.hist_code."
    },
    "public.trn_labour_issue": {
        "purpose": "Labour and service-related transaction information linked to invoices.",
        "population_status": "POPULATED",
        "important_fields": [
            "labour_issue_id", "inv_type", "inv_no", "inv_dt",
            "job_no", "cust_code", "hist_code", "tot_amt"
        ],
        "description": "Validated relationship to VSALE invoices for service/labour details."
    },
    "public.trn_insu_detail": {
        "purpose": "Insurance-related Sales transaction information.",
        "population_status": "POPULATED",
        "important_fields": [
            "insu_detail_id", "inv_type", "inv_no", "inv_date",
            "cust_code", "hist_code", "insu_amt"
        ],
        "description": "Validated relationship to VSALE invoices for insurance details."
    },
    "public.mst_product": {
        "purpose": "Product master definitions.",
        "population_status": "POPULATED",
        "important_fields": [
            "product_id", "product_code", "sub_prd_code",
            "co_prd_code", "product_name", "short_name", "class_code"
        ],
        "description": "Authoritative master for mapping user-friendly product names (e.g. 'JUPITER') to product codes (e.g. '0000026')."
    },
    "public.mst_ac_detail": {
        "purpose": "General Ledger (GL) account master.",
        "population_status": "POPULATED",
        "important_fields": [
            "ac_code", "ac_name", "ac_type", "group_code", "head_code"
        ],
        "description": "Authoritative master for GL account codes and account names."
    },
    "public.mst_salesman": {
        "purpose": "Salesman master.",
        "population_status": "POPULATED_MASTER_ONLY",
        "important_fields": [
            "salesman_id", "salesman_code", "salesman_name", "salesman_type"
        ],
        "description": "Salesman master table. Note: A valid VSALE invoice-level relationship to salesman has NOT been established."
    },
    "public.mst_financer": {
        "purpose": "Financer master.",
        "population_status": "POPULATED_MASTER_ONLY",
        "important_fields": [
            "financer_id", "financer_code", "financer_name", "financer_type"
        ],
        "description": "Financer master table. Note: A valid VSALE invoice-level relationship to financer has NOT been established."
    },
    "public.mst_sale_type": {
        "purpose": "Sale-type master.",
        "population_status": "POPULATED_MASTER_ONLY",
        "important_fields": [
            "sale_type_id", "sale_type_code", "sale_type_name"
        ],
        "description": "Sale-type master table. Note: A valid VSALE relationship has NOT been established."
    },
    "public.mst_customer_profile": {
        "purpose": "Customer master / profile.",
        "population_status": "EMPTY_TABLE",
        "important_fields": [
            "auto_id", "customer_code", "challan_no", "dealer_name", "dt_sale", "pur_model"
        ],
        "description": "Currently empty. Agent must NOT invent customer-master mappings from this table; use transaction/history customer codes instead."
    }
}

VALIDATED_SALES_FLOW: Dict[str, Any] = {
    "flow_description": "transection (inv_type='VSALE') -> VSALE invoice -> trn_jobcard.inv_no -> trn_jobcard.hist_code -> mst_history.hist_code -> mst_product.product_code",
    "accounting_to_vehicle_bridge": [
        "transection.inv_no == trn_jobcard.inv_no (where transection.inv_type = 'VSALE' AND trn_jobcard.inv_type = 'VSALE')",
        "trn_jobcard.hist_code == mst_history.hist_code",
        "mst_history.product_code == mst_product.product_code"
    ],
    "empirical_validations": [
        "VSALE invoice identifiers are aligned across relevant accounting invoice fields.",
        "All discovered VSALE invoices connect through the jobcard/history bridge.",
        "mst_history.hist_code is unique in the discovered data."
    ]
}

BUSINESS_RULES: List[str] = [
    "transection is the authoritative accounting source for Sales financial amounts.",
    "VSALE rows (inv_type = 'VSALE') are the relevant Sales accounting transaction type for the current Sales module.",
    "transection.doc_date is the authoritative Sales transaction date.",
    "transection.series is the authoritative voucher-series field.",
    "transection.ev is the authoritative EV/non-EV field.",
    "transection.co_year is the authoritative financial-year field.",
    "transection.ac_code is the authoritative accounting/GL account field.",
    "Accounting totals must be aggregated carefully before/independently of one-to-many history joins to avoid multiplication.",
    "One invoice can contain multiple vehicle/history rows.",
    "One invoice can contain multiple products.",
    "One invoice can contain multiple customers.",
    "One invoice can contain multiple EV/non-EV values.",
    "One invoice can contain multiple voucher series.",
    "Some invoices can span financial years.",
    "Do not assume invoice number alone uniquely identifies a single vehicle/product/customer context.",
    "When joining invoice-level accounting data with vehicle/history data, preserve the full invoice context and avoid silently dropping valid invoice-level accounting information."
]

VALIDATED_RELATIONSHIPS: List[Dict[str, str]] = [
    {
        "source": "transection (inv_type='VSALE')",
        "target": "trn_jobcard.inv_no",
        "join_condition": "transection.inv_type = 'VSALE' AND transection.inv_no = trn_jobcard.inv_no",
        "cardinality": "ONE_TO_MANY",
        "status": "VALIDATED"
    },
    {
        "source": "trn_jobcard.hist_code",
        "target": "mst_history.hist_code",
        "join_condition": "trn_jobcard.hist_code = mst_history.hist_code",
        "cardinality": "ONE_TO_ONE",
        "status": "VALIDATED"
    },
    {
        "source": "mst_history.product_code",
        "target": "mst_product.product_code",
        "join_condition": "mst_history.product_code = mst_product.product_code",
        "cardinality": "MANY_TO_ONE",
        "status": "VALIDATED"
    },
    {
        "source": "transection (inv_type='VSALE')",
        "target": "trn_labour_issue",
        "join_condition": "transection.inv_no = trn_labour_issue.inv_no AND trn_labour_issue.inv_type = 'VSALE'",
        "cardinality": "ONE_TO_MANY",
        "status": "VALIDATED"
    },
    {
        "source": "transection (inv_type='VSALE')",
        "target": "trn_insu_detail",
        "join_condition": "transection.inv_no = trn_insu_detail.inv_no AND trn_insu_detail.inv_type = 'VSALE'",
        "cardinality": "ONE_TO_MANY",
        "status": "VALIDATED"
    }
]

CANDIDATE_RELATIONSHIPS: List[Dict[str, str]] = [
    {
        "source": "mst_history.cust_code",
        "target": "transection.ac_code",
        "join_condition": "mst_history.cust_code = transection.ac_code",
        "status": "CANDIDATE_ONLY",
        "note": "Partial overlap observed; candidate for customer account linkage but not fully validated as a hard foreign key."
    }
]

NOT_VALIDATED_RELATIONSHIPS: List[Dict[str, str]] = [
    {
        "source": "VSALE invoice",
        "target": "mst_salesman.salesman_code",
        "status": "NOT_VALIDATED",
        "note": "Valid VSALE invoice-level relationship to salesman has NOT been established."
    },
    {
        "source": "VSALE invoice",
        "target": "mst_financer.financer_code",
        "status": "NOT_VALIDATED",
        "note": "Valid VSALE invoice-level relationship to financer has NOT been established."
    },
    {
        "source": "VSALE invoice",
        "target": "mst_sale_type.sale_type_code",
        "status": "NOT_VALIDATED",
        "note": "Valid VSALE relationship to sale-type master has NOT been established."
    },
    {
        "source": "VSALE invoice",
        "target": "mst_customer_profile.customer_code",
        "status": "NOT_VALIDATED",
        "note": "mst_customer_profile table is currently empty in database."
    }
]

ENTITY_MASTERS: Dict[str, Any] = {
    "product": {
        "source_table": "public.mst_product",
        "code_field": "product_code",
        "name_field": "product_name",
        "alias_fields": ["sub_prd_code", "co_prd_code", "short_name"],
        "status": "VALIDATED_MASTER"
    },
    "gl_account": {
        "source_table": "public.mst_ac_detail",
        "code_field": "ac_code",
        "name_field": "ac_name",
        "alias_fields": ["ac_type", "group_code"],
        "status": "VALIDATED_MASTER"
    },
    "customer": {
        "source_table": "mst_history / transection",
        "code_field": "cust_code",
        "name_field": "customer_name",
        "status": "TRANSACTION_EMBEDDED",
        "note": "mst_customer_profile is empty. Resolve customer codes/names directly from mst_history.cust_code and mst_history.customer_name or transection.ac_code."
    }
}

QUERY_GUIDANCE: Dict[str, Any] = {
    "financial_amounts_source": "public.transection (filter inv_type = 'VSALE')",
    "vehicle_details_source": "public.mst_history",
    "product_master_source": "public.mst_product",
    "account_master_source": "public.mst_ac_detail",
    "safe_filters": [
        "transection.doc_date",
        "transection.series",
        "transection.ev",
        "transection.co_year",
        "transection.ac_code",
        "mst_history.product_code",
        "mst_history.cust_code",
        "mst_history.chassis_no",
        "mst_history.engine_no",
        "mst_history.reg_no"
    ],
    "safe_grouping_dimensions": [
        "product_code",
        "cust_code",
        "series",
        "co_year",
        "ev",
        "ac_code",
        "doc_date",
        "inv_no"
    ],
    "pre_aggregation_rules": (
        "Calculate invoice/accounting totals from transection BEFORE joining 1-to-N "
        "trn_jobcard / mst_history rows to avoid duplicate sum multiplication."
    ),
    "one_to_many_joins": [
        "transection (VSALE) -> trn_jobcard",
        "trn_jobcard -> mst_history"
    ]
}

SALES_SCHEMA_CONTEXT: Dict[str, Any] = {
    "tables": SALES_TABLES,
    "validated_flow": VALIDATED_SALES_FLOW,
    "business_rules": BUSINESS_RULES,
    "validated_relationships": VALIDATED_RELATIONSHIPS,
    "candidate_relationships": CANDIDATE_RELATIONSHIPS,
    "not_validated_relationships": NOT_VALIDATED_RELATIONSHIPS,
    "entity_masters": ENTITY_MASTERS,
    "query_guidance": QUERY_GUIDANCE
}


def get_sales_schema_context() -> Dict[str, Any]:
    """
    Return the trusted Sales schema/business context dictionary.
    """
    return SALES_SCHEMA_CONTEXT
