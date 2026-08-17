# Backend Subscriptions

## 2.2 Store Product Validation

The store verification endpoint must accept every active subscription product
id. Apple currently has monthly and yearly products:

```python
VALID_PRODUCT_IDS = {"de.preismenu.monthly", "de.preismenu.yearly"}

if tx.productId not in VALID_PRODUCT_IDS:
    return Response({"error": "unexpected_product"}, status=400)
```

Set the subscription plan from the product id:

```python
PLAN_BY_PRODUCT_ID = {
    "de.preismenu.monthly": "monthly",
    "de.preismenu.yearly": "yearly",
}

subscription.plan = PLAN_BY_PRODUCT_ID[tx.productId]
```

Apply the same validation and plan mapping to the Google verify endpoint once
the Play products are created.
