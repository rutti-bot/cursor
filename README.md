# HubSpot → weclapp Sync (Make.com Scenario)

Make.com scenario blueprint for syncing HubSpot CRM data to weclapp ERP. The scenario is triggered by a webhook on deal changes and synchronizes companies, contacts, and deals (as sales orders) from HubSpot to weclapp.

## Scenario File

- `scenarios/frequent-sync.json` — the complete Make.com scenario blueprint (importable via Make.com)

## Flow Overview

```
Webhook (Deal Change)
  │
  ├─ Get Deal (HubSpot)
  ├─ List Associations (companies, contacts, line_items)
  ├─ Get Company (HubSpot)
  ├─ Get Contact (HubSpot)
  │
  └─ Router
      │
      ├─ Route 1: Customer Sync (Contact NEW in weclapp)
      │   ├─ Build customer JSON
      │   └─ Router
      │       ├─ POST /customer  (Company new)
      │       └─ PUT  /customer  (Company exists)
      │
      ├─ Route 2: Customer Sync (Contact EXISTS in weclapp)
      │   ├─ Build customer JSON
      │   └─ Router
      │       ├─ POST /customer  (Company new)
      │       └─ PUT  /customer  (Company exists)
      │
      └─ Route 3: Deal → Sales Order Sync
          ├─ Search line items by deal association (1 API call)
          ├─ Aggregator (collect all orderItems)
          ├─ Build salesOrder JSON
          └─ Router
              ├─ POST /salesOrder  (new order)
              │   └─ Update Deal in HubSpot with weclapp order ID
              └─ PUT  /salesOrder  (existing order)
```

## What Was Added (Deal → Sales Order Sync)

### Changes to Existing Modules

1. **Module 41 (List Associations)** — unchanged, fetches `companies` and `contacts` associations. Line items are retrieved separately via the Search CRM Objects module (110).

### New Modules (Route 3)

| Module ID | Type | Purpose |
|-----------|------|---------|
| 110 | `hubspotcrm:searchCRMObject` | Searches for line items associated with the deal (filter: `associations.deal = deal ID`). Returns all line items with their properties in one call — no separate iterator + getLineItem needed. The search module itself iterates and outputs one bundle per line item. |
| 112 | `builtin:BasicAggregator` | Aggregates the line items from module 110 into an `orderItems` array for the weclapp sales order |
| 113 | `json:CreateJSON` | Builds the weclapp `salesOrder` JSON body with customer data, addresses, deal data, and the aggregated order items |
| 114 | `builtin:BasicRouter` | Routes between creating a new sales order vs. updating an existing one |
| 115 | `http:MakeRequest` (POST) | Creates a new sales order in weclapp (`POST /webapp/api/v1/salesOrder`) |
| 116 | `http:MakeRequest` (PUT) | Updates an existing sales order in weclapp (`PUT /webapp/api/v1/salesOrder/id/{id}`) |
| 117 | `hubspotcrm:updateDeal` | After creating a new sales order, writes the weclapp order ID back to the HubSpot deal (property `id_weclapp_order`) |

### Data Mapping: HubSpot Deal → weclapp Sales Order

| weclapp Field | Source |
|---------------|--------|
| `customerId` | Company `id_weclapp` |
| `customerNumber` | Company `erp_number` |
| `commission` | Deal `dealname` |
| `description` | Deal `description` |
| `headerDiscount` | Deal `hs_discount_percentage` |
| `responsibleUserId` | Company `zustandiger_mitarbeiter_weclapp` |
| `salesChannel` | Company `vertriebsweg` |
| `recordCurrencyId` | Deal `deal_currency_code` |
| `invoiceAddress` | Company billing address (fallback to primary) |
| `deliveryAddress` | Company primary address |
| `hs_deal_id` | Deal ID (custom attribute for traceability) |

### Data Mapping: HubSpot Line Items → weclapp Order Items

| weclapp orderItem Field | HubSpot Line Item Property |
|------------------------|---------------------------|
| `articleId` | `hs_sku` |
| `articleNumber` | `hs_sku` |
| `title` | `name` |
| `description` | `description` |
| `quantity` | `quantity` |
| `unitPrice` | `price` |
| `discountPercentage` | `hs_discount_percentage` |
| `netAmount` | `amount` |
| `positionNumber` | Iterator index |

## Prerequisites

### HubSpot Custom Properties (on Deal)

- `id_weclapp_order` — stores the weclapp sales order ID for tracking existing orders

### weclapp Custom Attributes

- The scenario uses custom attributes on the weclapp customer entity (IDs `2440728`, `2440755`)
- The sales order endpoint requires the customer to exist in weclapp (identified by `customerId`)

### Connections & Credentials

- **HubSpot connection** (ID `3866929`): OAuth connection with CRM scopes including `crm.objects.line_items.read`
- **weclapp API key** (keychain ID `111569`): API key for `performanat.weclapp.com`

## How to Import

1. Go to your Make.com organization
2. Create a new scenario
3. Use the "Import Blueprint" feature (right-click on the canvas → Import Blueprint)
4. Paste the content of `scenarios/frequent-sync.json`
5. Re-map connections (HubSpot, weclapp API key)
6. Adjust the webhook URL and authentication token as needed

## Notes

- The `articleId` / `articleNumber` mapping currently uses `hs_sku` from HubSpot line items. If your HubSpot products use a different field to reference weclapp article IDs, update the mapping in module 112.
- The scenario runs all three routes in parallel (customer sync routes + deal-to-order route).
- The "Sales Order new" path (module 115 → 117) writes the new weclapp order ID back to HubSpot to prevent duplicate order creation on subsequent runs.
