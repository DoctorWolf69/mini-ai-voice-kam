"""Mini AI Voice KAM: mock seller data and the deterministic diagnosis.

Run `python server.py --check` to verify the numbers.
"""
from collections import Counter

# ---------------------------------------------------------------- mock data
# The five headline numbers come straight from the assignment.
# Everything under "detail" is an ASSUMPTION added to make the diagnosis concrete (see NOTE.md).
SELLER = {
    "seller": "Sharma Home Decor",
    "category": "Home & Kitchen",
    "catalogue_size": 60,
    "last_month": {"sales": 200000, "orders": 400, "cancellation_rate": 0.08, "avg_price": 500, "oos_products": 5},
    "this_month": {"sales": 135000, "orders": 270, "cancellation_rate": 0.14, "avg_price": 500, "oos_products": 18},
    "detail": {
        # 13 SKUs went out of stock this month. Last month they sold 150 orders; this month only 20 (before they ran out).
        "newly_oos_skus": [
            {"sku": "HD-101", "name": "Cotton bedsheet set (double)", "orders_last_month": 34, "orders_this_month": 4, "supplier": "Jaipur Textiles"},
            {"sku": "HD-107", "name": "Ceramic dinner set, 18 pc", "orders_last_month": 26, "orders_this_month": 3, "supplier": "Khurja Ceramics"},
            {"sku": "HD-112", "name": "Blackout curtains (pair)", "orders_last_month": 21, "orders_this_month": 3, "supplier": "Jaipur Textiles"},
            {"sku": "HD-118", "name": "Steel water bottle, 1 L", "orders_last_month": 17, "orders_this_month": 2, "supplier": "Rajkot Steelware"},
            {"sku": "HD-124", "name": "Cushion covers, set of 5", "orders_last_month": 14, "orders_this_month": 2, "supplier": "Jaipur Textiles"},
            {"sku": "HD-131", "name": "Bath towel set", "orders_last_month": 11, "orders_this_month": 2, "supplier": "Jaipur Textiles"},
            {"sku": "HD-133", "name": "Wall clock, wooden", "orders_last_month": 8, "orders_this_month": 1, "supplier": "Saharanpur Woodcraft"},
            {"sku": "HD-140", "name": "Kitchen storage jars, 6 pc", "orders_last_month": 6, "orders_this_month": 1, "supplier": "Rajkot Steelware"},
            {"sku": "HD-142", "name": "Table runner", "orders_last_month": 4, "orders_this_month": 1, "supplier": "Jaipur Textiles"},
            {"sku": "HD-147", "name": "Door mat, coir", "orders_last_month": 3, "orders_this_month": 1, "supplier": "Alleppey Coir"},
            {"sku": "HD-150", "name": "Fridge mats, set of 6", "orders_last_month": 2, "orders_this_month": 0, "supplier": "Rajkot Steelware"},
            {"sku": "HD-152", "name": "Napkin holder", "orders_last_month": 2, "orders_this_month": 0, "supplier": "Saharanpur Woodcraft"},
            {"sku": "HD-155", "name": "Coaster set", "orders_last_month": 2, "orders_this_month": 0, "supplier": "Saharanpur Woodcraft"},
        ],
        "other_skus_orders": {"last_month": 250, "this_month": 250},  # everything still in stock sold the same
        # Orders are counted gross (before cancellations). Reasons for cancelled orders:
        "cancellation_reasons": {
            "last_month": {"item_unavailable": 6, "dispatch_delay": 10, "customer_changed_mind": 16},
            "this_month": {"item_unavailable": 22, "dispatch_delay": 9, "customer_changed_mind": 7},
        },
        # Illustrative visibility signal for the in-stock catalogue
        "search_impressions": {"last_month": 52000, "this_month": 44200},
    },
}

def diagnose():
    """Deterministic diagnosis. The LLM explains it; it never does the arithmetic."""
    lm, tm, d = SELLER["last_month"], SELLER["this_month"], SELLER["detail"]
    pct = lambda a, b: round((b - a) / a * 100, 1)
    oos = d["newly_oos_skus"]
    lost_oos_orders = sum(s["orders_last_month"] - s["orders_this_month"] for s in oos)
    order_drop = lm["orders"] - tm["orders"]
    cancels_last = round(lm["orders"] * lm["cancellation_rate"])
    cancels_this = round(tm["orders"] * tm["cancellation_rate"])
    unavailable = d["cancellation_reasons"]["this_month"]["item_unavailable"]
    top = sorted(oos, key=lambda s: -s["orders_last_month"])
    suppliers = dict(Counter(s["supplier"] for s in oos))

    issues = [
        {
            "rank": 1,
            "issue": "Stock-outs on best sellers",
            "evidence": f"Out-of-stock products rose {lm['oos_products']} to {tm['oos_products']}. "
                        f"The {len(oos)} newly out-of-stock SKUs lost {lost_oos_orders} orders, "
                        f"which is {round(lost_oos_orders / order_drop * 100)}% of the {order_drop}-order drop.",
            "revenue_impact_inr": lost_oos_orders * tm["avg_price"],
            "restock_first": [{"sku": s["sku"], "name": s["name"], "supplier": s["supplier"],
                               "orders_lost": s["orders_last_month"] - s["orders_this_month"]} for s in top[:3]],
            "restock_first_orders_lost_total": sum(s["orders_last_month"] - s["orders_this_month"] for s in top[:3]),
            "suppliers_affected": suppliers,
        },
        {
            "rank": 2,
            "issue": "Cancellations up, mostly from unavailable items",
            "evidence": f"Cancellation rate went {lm['cancellation_rate']:.0%} to {tm['cancellation_rate']:.0%} "
                        f"({cancels_last} to {cancels_this} orders). {unavailable} of {cancels_this} cancellations "
                        f"this month were 'item unavailable', up from {d['cancellation_reasons']['last_month']['item_unavailable']}.",
            "revenue_impact_inr": cancels_this * tm["avg_price"],
        },
        {
            "rank": 3,
            "issue": "Visibility risk",
            "evidence": f"Search impressions fell {abs(pct(d['search_impressions']['last_month'], d['search_impressions']['this_month']))}%. "
                        "Stock-outs and seller-side cancellations usually lower search ranking, so this can get worse next month.",
        },
    ]
    return {
        "sales_change_pct": pct(lm["sales"], tm["sales"]),
        "orders_change_pct": pct(lm["orders"], tm["orders"]),
        "avg_price_change_pct": pct(lm["avg_price"], tm["avg_price"]),
        "headline": "Volume problem, not a pricing problem: price is flat and sales fell exactly in line with orders.",
        "root_cause": "Stock-outs on top SKUs. They lose orders directly, cause 'item unavailable' cancellations, and hurt visibility.",
        "not_the_cause": ["Pricing (avg price flat at ₹500)", f"In-stock SKUs (still {d['other_skus_orders']['this_month']} orders, unchanged)"],
        "issues": issues,
    }


if __name__ == "__main__":
    d = diagnose()
    assert d["sales_change_pct"] == -32.5 and d["orders_change_pct"] == -32.5 and d["avg_price_change_pct"] == 0
    assert "130 orders" in d["issues"][0]["evidence"] and "100%" in d["issues"][0]["evidence"]
    assert sum(s["orders_this_month"] for s in SELLER["detail"]["newly_oos_skus"]) + 250 == 270
    assert len(SELLER["detail"]["newly_oos_skus"]) + SELLER["last_month"]["oos_products"] == 18
    assert sum(SELLER["detail"]["cancellation_reasons"]["this_month"].values()) == round(270 * 0.14)
    assert sum(SELLER["detail"]["cancellation_reasons"]["last_month"].values()) == round(400 * 0.08)
    print("self-check OK:", d["headline"])
