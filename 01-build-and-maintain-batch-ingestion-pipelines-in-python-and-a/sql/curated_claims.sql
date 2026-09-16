SELECT
    claim_id,
    insurer_id,
    business_date,
    member_token,
    provider_id,
    CASE raw_status
        WHEN 'P' THEN 'PAID'
        WHEN 'D' THEN 'DENIED'
        ELSE raw_status
    END AS claim_status,
    paid_amount,
    member_liability,
    paid_amount - member_liability AS net_paid_amount
FROM landing_claims