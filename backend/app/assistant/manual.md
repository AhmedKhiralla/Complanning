# Complanning User Manual


## 1. About Complanning and this manual

Complanning turns your master data, rules, sales plan and stock into a finite-capacity production plan you can edit, release and audit. It is a product of Comp11 Labs, built for pharmaceutical plants first and usable by any manufacturer.

This manual follows the order you set the system up in: company and users, then master data, then planning rules, then demand and stock, then plans. Each setting is described with what it does and what changes when you choose it. Words in **bold** are the labels you see on screen.

### What each part feeds

| Part | You maintain | The planning engine uses it to |
| --- | --- | --- |
| Items, units, markets, prices | What you make and buy, units, sales limits, price history | Know what is produced, convert quantities, cap demand, value deliveries |
| Bills of materials | Recipes per product, by version | Turn a product batch into the batches and materials it needs |
| Machines, routings, calendar | Equipment, process steps, shifts, holidays, downtime | Know where and when each step can run and how long it takes |
| Planning rules | Changeovers, campaigns, hold times, QC times | Add cleaning time, limit runs, respect waiting and holding times |
| Sales plan and stock | Monthly demand per market, stock by lot and QC status | Decide what to make, how much and by when |
| Production plans | Objective and options per run | Build, edit, compare and release the schedule |

The sequence of work, from setup to a released plan, is drawn below.

&#91;embedded content: setup to released plan · 9 steps\]

Setup is done once and kept up to date; the six steps of the cycle repeat every month, or whenever demand, stock or machines change. Numbers in brackets are the sections of this manual.

### Two things to know first

- **Everything is per site or per company.** Products, materials, bills of materials, prices and markets belong to the whole company. Machines, routings, calendars, rules, sales plan, stock and plans belong to one site, chosen in the **Site** selector at the top of the screen.
- **Every change is recorded.** Complanning keeps an audit trail of who changed what, when, with the value before and after. Nothing in it can be edited or deleted. See section 14.

## 2. Getting started

> **New to Complanning?** Follow the [Getting Started Tutorial](https://claude.ai/artifact/WfDYAw4AFdLL9CgEBKs1VG) first: twelve steps with one worked example, from first sign-in to a released plan. In the website, the **Get started** checklist on Home and the short tour on each page follow the same steps.

### Signing in

1. Open the Complanning address your company uses, for example complanning.comp11labs.com.
2. Enter your email and password, then **Sign in**.
3. On your first sign-in, and after an administrator resets your password, you must choose a new password before you can do anything else. The temporary password works only for that change.

What can stop a sign-in:

- **Wrong password too many times.** After the number of failed attempts set by your company (default 5), the account locks for the lockout time (default 30 minutes). An administrator can unlock it sooner.
- **Password expired.** After the expiry period (default 90 days) you are asked for a new password at sign-in.
- **Account disabled.** Only an administrator can enable it again.

### Passwords

Your company's password rules are shown next to the password box. With the defaults a password needs at least 10 characters, an upper-case letter, a lower-case letter, a digit and a symbol, and it cannot repeat any of your last 5 passwords. To change it at any time, open your name at the top right and choose **Change password**.

### Sessions

If you do nothing for the session timeout (default 30 minutes), you are signed out and must sign in again. Unsaved changes on screen are lost, so save before you step away. **Sign out** in the user menu ends the session immediately.

### Language and theme

Open your name at the top right:

| Choice | Options | Effect |
| --- | --- | --- |
| Language | English, العربية | Arabic turns the whole screen right to left. Codes, numbers and dates stay in Latin digits so they match plant documents. Your choice is saved to your account and follows you to any computer. |
| Theme | Light, Dark, System | System follows your computer's setting. Saved to your account. |

A new user starts in the company's **Default language for new users** (Company settings).

### The screen

- **Menu (left):** Home; Planning (Production plans, Sales plan, Stock, Net requirements); Master data (Items and materials, Units and markets, Bills of materials, Machines, Routings, Working calendar); Rules (Changeovers, Campaigns and hold times, Holding and QC times); Administration (Users, Sites, Company settings, Audit trail) for administrators. On a phone the menu opens from the button at the top left.
- **Site selector (top):** every site-level page shows the site chosen here. Changing it changes what you see on Machines, Routings, Calendar, Rules, Sales plan, Stock, Net requirements and Production plans. You only see sites where you have a role.
- **Home:** a checklist that walks a new company through setup, with links to each step.

Times are shown in the site's time zone. Each schedule page names the time zone it uses.

## 3. Roles and permissions

A user's rights come from roles given per site, plus the company administrator flag. A person can hold different roles at different sites, for example planner at one plant and viewer at another.

| Role | Given | Can change | Can read |
| --- | --- | --- | --- |
| Platform administrator | Comp11 Labs only | Companies and their administrators | Company list and the platform audit trail; never a company's business data |
| Company administrator | Per user, for the whole company | Everything in the company: users, sites, settings, all master data, rules, sales plan, stock and plans at every site; loads sample data | Everything, including the audit trail |
| Master-data editor | Per site | Company-wide master data (items, units, markets, prices, bills of materials, cleaning groups, holding and QC times) once they are editor at any site; machines, downtime, routings, calendar and rules at their sites | All data at their sites |
| Planner | Per site | Sales plan, stock and production plans (make, move, lock, re-plan, release) at their sites | All data at their sites |
| Viewer | Per site | Nothing | All data at their sites |

Impact of the split: QA can own master data as master-data editors while planners own the plan, which keeps validated data separate from day-to-day planning. A screen you can only read shows a note saying so, and its edit buttons are hidden.

## 4. Platform administration (Comp11 Labs)

The platform administrator creates each customer company and its first administrator; from then on the company manages itself. The platform administrator never sees a company's products, plans or other business data.

### Creating a company

Open **Companies** and choose **New company**.

| Field | Effect |
| --- | --- |
| Code | Short unique code, 2 to 20 characters. Fixed after creation. |
| Name | Shown in the menu header and on exports. The company can change it later. |
| Country and time zone | Defaults for the company's first site and for dates. Egypt and Africa/Cairo by default. |
| Default language | The language new users of this company start in. |
| Preset | **Pharmaceutical** switches on all quality features (lots, assay, QC times, release at risk, cleaning verification, equipment and product hold times). **General manufacturing** switches them off. The company can change every switch later in Company settings. |
| Administrator email and name | The company's first administrator. |

When you save, Complanning shows the administrator's temporary password once. Copy it and send it to the person securely; it cannot be shown again. The standard units of measure are created for the company at the same time.

### Looking after companies

- **Suspend** a company to stop all its users signing in; their data is kept. Set it back to active to restore access.
- **Administrators:** add another administrator, or **Reset password** for one who lost theirs. A reset shows a new temporary password once and forces a change at the next sign-in.
- The platform **Audit trail** shows platform-level events: companies created or changed, administrator resets and platform sign-ins.

The platform administrator account itself is created when Complanning is installed, from the hosting settings. Remove the start-up password from the hosting settings after the first sign-in.

## 5. Company setup (company administrators)

Set up the company in this order: Company settings, Sites, Users. **Administration** in the menu holds all three.

### 5.1 Company settings › Company

| Field | Effect |
| --- | --- |
| Name | Shown in the menu header, on exports and in the audit trail. The code is fixed. |
| Country, time zone | Company defaults. Each site has its own country and time zone, which are the ones planning uses. |
| Default language for new users | The language a new user starts in. Each user can switch afterwards. |

**Cost currency** (shown when Cost calculation is on): the currency of every item's standard cost. Margin is calculated only for markets that sell in this currency; other markets show sales value without margin.

### 5.2 Company settings › Features

Switches turn whole parts of planning on or off for every site. **Apply preset** sets all of them at once: **Pharmaceutical preset** (all quality features on) or **General manufacturing preset** (quality features off). Click **Save changes** to apply.

| Feature | When on | When off |
| --- | --- | --- |
| Stock by lot | Stock lines carry lot number, manufacturing and expiry dates, assay and LOD; expiring lots are flagged. | Stock is one quantity per item and status, without lot columns. |
| Use work-in-process stock | WIP stock is subtracted before new WIP batches are planned. | WIP stock is ignored; every WIP need becomes batches. |
| Use semi-finished stock | Semi-finished stock is subtracted before new batches. | Ignored. |
| Use finished product stock | Finished stock is subtracted from the sales plan before planning. | The full sales plan is produced, whatever is in the warehouse. |
| QC lead times | Batches wait for their QC release time before the next stage or before sale; materials in quarantine wait for theirs. | No QC waiting anywhere; the Holding and QC times page hides the QC column. |
| Release at risk | Plans may offer **Allow release at risk** for items that permit it. | The option is hidden and never applied. |
| Cleaning verification | Changeover rules carry visual, rinse or swab checks and a results wait that blocks the machine. | Verification and its wait are ignored; changeovers are cleaning and format time only. |
| Clean and dirty equipment hold times | Machines carry hold times; a machine idle beyond its clean hold is re-cleaned before use. | No hold times; the fields and page section are hidden. |
| Product holding times | Minimum wait and maximum hold between stages are applied and checked. | Ignored; columns hidden. |
| Campaign limits | Maximum batches or days in a row force a full clean; the Campaigns section is shown. | No campaign limits. |
| Assay compensation, Overage, Compensating material | Assay compensation: assay-compensated formula lines are raised by the average potency of the usable lots (100 ÷ assay, and 100 ÷ (100 − LOD) for materials whose assay is reported on the dried substance). Overage: the registered excess is added. Compensating material: the filler or q.s. line gives up the extra assay weight so the batch stays the same. All three change Net requirements and plans; their bill-of-materials columns are shown. | Formula quantities are used as written: no potency adjustment, no overage, no reduction of the compensating line. The matching columns and the Lot check panel are hidden; stored values are kept. |
| Sales plan, Holiday import, Cost calculation | Sales plan: plans and requirements use the sales plan lines. Holiday import: the calendar offers Import holidays. Cost calculation: standard cost on every item, cost currency in Company, material cost and margin in plans, suggested-order value in Net requirements, and the Sales value objective ranks by margin. | Sales plan: every finished product with a routing at the site is planned at its maximum sellable quantity per market for each month that ends in the horizon; the Sales plan page shows a notice. Holiday import: the button is hidden and the import is refused; add days off by hand. Cost calculation: cost fields and figures are hidden. |

Changing a switch does not change plans already made. Make or re-plan a plan to see its effect.

### 5.3 Company settings › Terminology

Rename seven words used across the screens, in English and Arabic: Batch, Work in process, Semi-finished product, Finished product, QC release, Campaign, Machine. Leave a box empty to keep the default. The change affects labels only, never data or exports' column names.

### 5.4 Company settings › Password and sessions

These are the 21 CFR Part 11 sign-in controls. Changes apply at each user's next sign-in or password change.

| Setting | Default | Allowed | Impact of a higher value |
| --- | --- | --- | --- |
| Minimum length | 10 | 8–64 | Stronger passwords, harder to remember |
| Require upper case, lower case, digit, symbol | All on | On or off each | Each rule switched off weakens passwords |
| Expiry (days) | 90 | 0–365; 0 = never | Fewer forced changes; 0 removes expiry |
| Password history | 5 | 0–24 | More old passwords that cannot be reused |
| Failed attempts before lock | 5 | 3–10 | More guesses allowed before the account locks |
| Lockout (minutes) | 30 | 5–1440 | Longer wait before a locked user can retry |
| Session timeout (minutes) | 30 | 5–240 | Users stay signed in longer when idle |

### 5.5 Sites

A site is one plant. Machines, routings, calendars, rules, sales plan, stock and plans all belong to a site.

| Field | Effect |
| --- | --- |
| Code | Short code shown in the site selector and file names. Fixed after creation. |
| Name, address | Display only. |
| Country | Chooses the national holidays proposed by **Import holidays** on the Working calendar. |
| Time zone | All shift times, schedules and dates on screen and in exports use it. Change it only if the site really moved: shifts keep their clock times. |
| Active | An inactive site disappears from the site selector; its data is kept. |

### 5.6 Users

**New user** asks for email, full name, **Company administrator** (on or off) and roles per site. On save the temporary password is shown once; give it to the user securely. They must change it at first sign-in.

| Action | Effect |
| --- | --- |
| Edit roles | Takes effect at the user's next page load. Removing all roles at a site removes that site from their selector. |
| Company administrator | Full rights in the company, at every site. Give it to as few people as possible. |
| Reset password | Shows a new temporary password once; the old password stops working. |
| Unlock | Clears a lockout after too many failed sign-ins. |
| Disable | The user can no longer sign in; their name stays on everything they did. Users are never deleted, so the audit trail stays complete. |

## 6. Master data: units, markets, prices and items

Master data is company-wide: one item list serves every site. Company administrators and master-data editors change it; everyone else reads it.

### 6.1 Units of measure

**Master data › Units and markets** lists the units. Standard units (KG, G, L, ML, EA, TAB, BLS, CTN, BOX and others) are created with the company and cannot be removed.

| Field | Effect |
| --- | --- |
| Dimension | Mass, volume, count, time, energy, gas or other. Units convert freely within a dimension. |
| Size in base unit | How many base units one of this unit holds (1 G = 0.001 KG). Wrong values scale every quantity that uses the unit. |
| Active | Inactive units cannot be chosen for new data. |

Three kinds of conversion happen automatically:

- **Same dimension:** by size (KG to G).
- **Mass to volume:** through the item's **Density (kg/L)**. Without a density, a bill of materials that mixes kg and L for that item is refused.
- **Count units:** through the item's own pack conversions (item sheet › **Units** tab), for example 1 BOX = 100 CTN or 1 CTN = 2 BLS. Without a conversion, quantities in that unit cannot be converted.

### 6.2 Markets

A market is a place you sell to, with its currency, for example LOCAL (EGP), MOH tender (EGP), KSA export (USD). Prices and sales limits are set per product and market. An inactive market drops out of the sales plan.

### 6.3 Products in markets and sales limits

On a finished product, the **Markets** tab lists the markets it is sold in.

| Field | Effect |
| --- | --- |
| Market | Only listed markets appear for this product in the sales plan. |
| Max sellable per month | The most you can sell there in a month. Sales plan cells above it turn orange with a warning; plans cut demand to it when **Cap demand at the sales limit** is on. Empty = no limit. |
| Min remaining shelf life (%) | Share of total shelf life that must remain on the due date. Finished stock lots below it are not used for this market (warning in the plan, "too short-dated" in Net requirements); new batches that would arrive below it raise a warning. |
| Active | An inactive product-market pair leaves the sales plan. |

### 6.4 Prices with history

Prices are never overwritten. **Add price** asks for market, price and **Valid from**. The current price for that market ends automatically the day before the new one starts, and overlapping periods are refused. **End price** closes a price without a successor.

Impact: every plan values its deliveries with the price valid on the plan's creation date. The sales plan and net requirements value at today's price. Old prices stay visible with their periods for audit.

### 6.5 Items and materials

**Master data › Items and materials** holds everything you buy or make. **New item** opens the item sheet.

| Type | Meaning | Planning treats it as |
| --- | --- | --- |
| Raw material | API, excipients, solvents | Bought: checked against stock, ordered with lead time |
| Packaging material | Film, foil, cartons, leaflets, bottles | Bought, same as raw material |
| Work in process | Granules, blends, bulk liquids | Made: needs a bill of materials and a routing |
| Semi-finished product | Blisters, filled bottles | Made |
| Finished product | The sold pack | Made; sold in markets |

The type cannot change after creation, because bills of materials and plans depend on it.

**General tab**

| Field | Effect |
| --- | --- |
| Item code | Unique, up to 40 characters; fixed after creation. Used in Excel import to match rows. |
| Name in English / Arabic | Shown in the user's language; English is used when Arabic is empty. |
| Stock unit | The unit stock, requirements and batch sizes are counted in. Choose carefully: it cannot change by import, and changing it later rescales nothing for you. |
| Dispensing unit | The unit materials are weighed or measured in, for example L for a liquid stocked in kg. Needs a density when it is a different dimension. |
| Density (kg/L) | Lets kg and L convert for this item. |
| Grade, Description, Dosage form | Reference only. |
| Cleaning group | Produced items only. Chooses which changeover rules apply between this product and others (section 9). Empty = only same-product, product-pair and "any other change" rules can apply. |
| Active | Inactive items keep their history and cannot be added to new bills of materials. An item that an active bill of materials still uses keeps being planned: switching it off asks you to confirm and names those BOMs, and plans and net requirements warn about it until you activate new versions without it. |

**Planning tab**

| Field | Applies to | Effect |
| --- | --- | --- |
| Purchase lead time (days) | Bought items | Earliest arrival of a missing material = today + lead time + QC release. Empty = shortage shown with no arrival date. |
| QC release after receipt (days) | Bought items | Added to the lead time, and the wait before quarantine stock becomes usable. |
| Minimum order quantity | Bought items | Suggested orders in Net requirements (shortage plus the top-up to safety stock) are never less than this. |
| Not stock-controlled | Bought items | For material made on site with no stock limit, such as purified water: never reported short. |
| Safety stock | All | Produced items: planning makes enough to keep this much in stock. Bought items: flagged **Below safety stock** when the plan would take stock under it. |
| Release testing time (days) | Produced items | QC time after a batch ends before the next stage may use it (unless released at risk), and before sale when **Test before sale** is on. |
| Shelf life (months), Standard cost, Pack size, Units per shipper | Finished or semi-finished | Shelf life gives planned batches an expiry (end of production + shelf life) and fills in lot expiry where only a manufacturing date was entered; expired lots are never used. Standard cost feeds cost figures when Cost calculation is on (all item types). Units per shipper: plans round deliveries to full shippers (option Full shippers only). Pack size: units per pack, shown in the plan export. |
| Test before sale | Finished products | On: a finished batch can ship only after its release testing time. Off: it can ship when it ends. |

**Assay reported on** (raw materials, shown when Assay compensation is on): *Substance as received* uses only the lot's assay; *Dried substance* also divides by (100 − the lot's loss on drying). For example, paracetamol at 99.6 % assay and 0.3 % LOD on the dried basis needs 750 × 100/99.6 × 100/99.7 = 755.3 kg instead of 750 kg, and the compensating filler is reduced by the extra 5.3 kg.

The **Usage** tab shows every bill of materials that uses the item.

## 7. Bills of materials

A bill of materials (BOM) says what one batch of a produced item consumes and how much it yields. Multi-level products chain them: a finished pack uses blisters, blisters use the blend, the blend uses raw materials.

### 7.1 Versions and status

| Status | Meaning | Can edit |
| --- | --- | --- |
| Draft | Being prepared or changed | Yes |
| Active | The version planning uses; one per item | No |
| Archived | A former active version, kept for history | No |

- **New bill of materials** (or **New version** on an item that has one) creates a draft, copied from the active version when there is one.
- **Activate** asks for a **Valid from** date. The draft becomes active; the previous active version is archived and ends the day before. The date can be the same day the previous version started (the new version replaces it that day), but not earlier; if it is, the dialog stays open and says which date to choose.
- **Discard draft** removes a draft that was never activated.

Impact: planning, net requirements and plans always use the active version. Editing a draft changes nothing until it is activated, so QA can prepare a change safely.

### 7.2 Header

| Field | Effect |
| --- | --- |
| Batch size and unit | Nominal quantity of one batch. Converted to the item's stock unit for planning. |
| Yield (%) | Expected output = batch size × yield. A 24,000 CTN batch at 99.5% plans 23,880 CTN. Lower yield means more batches for the same demand. |
| Batch mode: Fixed | Every batch is full size. Demand of 1.2 batches becomes 2 full batches; the extra goes to stock. |
| Batch mode: Partial, with Min batch (%) | The last batch may be smaller, down to the minimum. With 50%, a need of 9,800 against a 23,880 batch plans one batch of 11,940 (the minimum). |
| Notes | Reference only. |

### 7.3 Lines

Each line is one component per batch.

| Field | Effect |
| --- | --- |
| Component | Any active item except the BOM's own item. A component that would contain the parent (a loop) is refused. |
| Quantity and unit | Per nominal batch. A different unit from the component's stock unit is converted (density or pack conversion needed across dimensions). |
| Overage (%) | Registered excess, for example 8% extra vitamin C for stability. Requirements = quantity × (1 + overage ÷ 100) everywhere in planning. |
| Assay-compensated | The quantity is adjusted to each lot's assay and loss on drying (LOD) when dispensing. Planning uses the standard quantity; the **Check a lot** tool shows the adjusted one. |
| Compensating | One line per BOM, usually a filler or q.s. water. It absorbs the difference created by assay compensation so the batch weight or volume stays constant. |

The adjusted quantity of an assay-compensated material is:

```latex
\text{actual} = \text{standard} \times \frac{100}{\text{assay}} \times \frac{100}{100 - \text{LOD}} \times \left(1 + \frac{\text{overage}}{100}\right)
```

### 7.4 Checking a BOM

- **Structure** shows the whole tree below the item with quantities and the number of lower-level batches needed, so you can check a multi-level product at a glance.
- **Check a lot** takes a lot's assay and LOD and shows how much of the material and of the compensating line one batch would use.

## 8. Machines, routings and the working calendar

These are site data: they describe where, when and how fast each step can run at the selected site.

### 8.1 Machines

**Master data › Machines**, grouped by area.

| Field | Effect |
| --- | --- |
| Code, Name | Code is fixed after creation and appears on the Gantt chart. |
| Type | Machine, QC laboratory, Room or Operator group. Any type can be put in a routing step and is then scheduled like a machine. Changeover rules are set for type Machine. |
| Area, Location | Area groups machines on screens and on the plan chart. Location is reference only. |
| Efficiency (%) | Every run time on this machine is divided by it. At 85%, a 60-minute step takes 71 minutes. Use it for the gap between rated speed and real output. |
| Dirty hold (h), Clean hold (h) | Shown when equipment hold times are on. Clean hold: if the machine stays idle longer than this after cleaning, the plan adds a re-clean before the next batch. Dirty hold: recorded; the plan always cleans right after a batch, so it is not exceeded. |
| Active | Inactive machines are never planned. Steps that only list inactive machines leave their batches unscheduled. |

**Planned downtime** (below the machine list): **Add downtime** with machine, from, to, reason (maintenance, calibration, qualification, breakdown, other) and notes. The time is removed from that machine's calendar and drawn as a red hatched block on plans. Remove an entry when the work is cancelled.

### 8.2 Routings

A routing lists the steps that make one batch of a produced item at this site, in order. **Master data › Routings**, then **New routing** or a product.

| Setting | Effect |
| --- | --- |
| Steps and their order | Steps run in sequence: a step starts only after the previous one ends, unless it runs with the previous step. Drag the arrows to reorder. |
| Per batch (minutes) | The step takes this long whatever the batch size, for example granulation 90 minutes. |
| Per hour (output rate) | Time = batch quantity ÷ rate, in the item's stock unit per hour, for example 6,000 CTN per hour. A smaller partial batch runs shorter. |
| Setup (min) | Added to every batch of the step, on top of the run time. |
| No pause | Off: the step pauses outside working time and resumes at the next shift. On: the step is placed only where it fits inside one unbroken block of working time. A step longer than any block leaves its batches unscheduled. |
| Runs with previous step | For steps after the first. On: the step runs at the same time as the step before it, on its own machine, for example a cartoner connected to a blister machine. The plan books both machines for the same start and end, as long as the slower of the two needs, and the editor shows a double bar between the steps instead of an arrow. The two steps cannot share a machine. If either step has No pause, both are placed without a pause. |
| Machines | Drag machines from the left, or use **Add machine**. Every machine listed is qualified. |
| Preferred (star) | The usual machine, listed first and used for lead-time estimates. The engine still tries every qualified machine and takes the one that finishes the step earliest. |
| Own minutes or own speed | Overrides the step's time for one machine, for example a slower second press. Empty = the step's time. |

The card under each step shows the time per batch on the preferred machine. A produced item without a routing at the site cannot be scheduled there.

**Connected machines and products packed two ways.** When a blister machine and a cartoner are connected, either give the item one step on one machine record that stands for both, or keep them as two machines with two steps and switch on **Runs with previous step** for the cartoning step. With the second way each machine has its own schedule and utilization. A product whose blisters are packed by hand gets its own blister semi-finished item, with a routing that uses only the blister machine, and a finished item packed on the manual packing line. Both finished items can use the same bulk product in their BOMs, each with its own packaging materials.

### 8.3 Working calendar

**Master data › Working calendar** sets when the site works.

| Part | How to set it | Effect on planning |
| --- | --- | --- |
| Default shifts | Per weekday: name, start, end. An end at or before the start ends the next day (night shift). | Steps run only inside shifts. Back-to-back shifts (07:00–15:00 and 15:00–23:00) count as one unbroken block. |
| Periods | A date range with its own shifts, for example Ramadan. | Inside the range the period's shifts replace the default ones. A period with no shifts uses the default. |
| Holidays | **Add holiday** by hand, or **Import holidays** for the site's country. | Only **confirmed** holidays stop production for the whole day. |

Imported holidays come from a public holiday service, or a built-in Egyptian list for 2026–2027 when the service has no data. Islamic holidays are marked **estimated** because their dates are announced late: confirm each one when the date is official. Until confirmed, the plan works that day. The month view shows the working hours per day after shifts, periods and holidays.

A site with no shifts at all is planned around the clock, and every plan says so in its warnings.

## 9. Planning rules

Rules tell the engine what happens between batches: cleaning, limits on long runs, and how long products and machines may wait. Rules are per site, except cleaning groups and the Holding and QC times page, which are company-wide.

### 9.1 Cleaning groups

A cleaning group is a set of products that share cleaning rules, for example PCM (paracetamol solids) and VITC (vitamin C liquids). Create groups at the top of **Rules › Changeovers**, then set each produced item's group on **Holding and QC times** or the item sheet. A group used by an item or rule cannot be deleted; make it inactive instead.

### 9.2 Changeover rules

A changeover is the time a machine is unavailable between two batches.

| Rule kind | Applies when the next batch is | Example |
| --- | --- | --- |
| Same product again | The same product | 30 min line clearance |
| Within a cleaning group | Another product of the same group | 2 h 30 min |
| Group to group (a matrix cell) | A product of another group, in that direction | PCM → VITC 28 h |
| Product pair | That exact product after that exact product | Egypt → KSA carton artwork, 35 min |
| Any other product change | Anything no other rule covers | 8 h |

Each rule has these parts:

| Field | Effect |
| --- | --- |
| Cleaning (min) | Working time; the machine is cleaned only inside shifts. |
| Format change (min) | Working time for change parts, tooling or artwork. |
| Cleaning verification | None, Visual, Rinse sample or Swab sample. Shown when cleaning verification is on. |
| Waiting for results (min) | Elapsed time, day and night, during which the machine stays blocked until results are released. |
| Notes | Reference only. |

Total changeover = cleaning + format change + waiting. The engine chooses the rule in this order, most specific first:

1. The same product again uses **Same product again**.
2. A **Product pair** rule for exactly these two products.
3. **Within a cleaning group** for this group, then for any group, when both products share a group; or the **Group to group** cell when they are in different groups.
4. **Any other product change**.
5. No rule found: no changeover time.

At every step a rule written for the specific machine beats the same rule for **All machines at this site**. Use the **Rules for** selector to switch between site rules and one machine's rules. A faded matrix cell is using a general rule; click it to write a specific one, which starts from the value in force.

**Check a changeover** at the bottom of the page picks a machine and two products and shows the rule that applies, its parts and the total. Use it to test rules before planning.

**Load sample rules** (company administrators, site without rules) adds the sample groups and rules for the sample products.

### 9.3 Campaign limits

**Rules › Campaigns and hold times**, shown when campaign limits are on. One line per product and machine (or all machines).

| Field | Effect |
| --- | --- |
| Max batches | After this many batches of the product in a row on the machine, the next one needs a full clean: the site's **Any other product change** rule (or the within-group rule if there is none). |
| Max days | Same, after this many days since the campaign started. |
| Min batches | The engine makes the item's batches in groups of at least this size, scheduled back to back on the machine. A shorter run (for example when fewer batches are needed) shows a Campaign short warning. |

### 9.4 Equipment hold times

The same page lists each machine's **Dirty hold** and **Clean hold** in hours, editable together, with **Save hold times**. Effect as in section 8.1.

### 9.5 Holding and QC times

**Rules › Holding and QC times** is one editable table for every produced item. Change any cells, then **Save changes**; **Cancel** discards them.

| Column | Effect |
| --- | --- |
| Cleaning group | Which changeover rules apply (9.2). |
| Min wait (h) | Time that must pass after a batch ends before the next stage may start, such as cooling or settling. |
| Max hold (h) | The validated hold time. The engine treats it as a deadline for the next stage, does not let one batch's leftover serve a need beyond it, and warns when a batch is held longer. |
| QC release (days) | Release testing time before the next stage may use the batch. Shown when QC lead times are on. |
| Release at risk | The next stage may start before QC results, when a plan is made with **Allow release at risk**. Shown when release at risk is on. |
| Test before sale | Finished products only: shipping waits for the QC release time. |

The next stage may start at: end of the batch + min wait + QC release (QC release is skipped when released at risk).

## 10. Sales plan, stock and net requirements

These three pages tell the engine what is needed and what you already have. Planners of the site and company administrators change the sales plan and stock; everyone with a role at the site can read them.

### 10.1 Sales plan

**Planning › Sales plan** is a grid: one row per finished product and market, one column per month.

| Control | Effect |
| --- | --- |
| Month arrows, **This month** | Move the window; edits in other months are kept until you save or discard. |
| 3, 6 or 12 months | Columns shown. |
| Market filter, search | Narrow the rows shown; totals follow the filter. |
| A cell | Quantity due that month, in the product's stock unit. Empty or 0 removes the month. Orange with ⚠ = above the market's monthly sales limit. |
| Calendar button in a cell | **Delivery details**: **Due date** inside the month and notes. With a due date the plan must deliver by that day; without one, by the end of the month. A blue button means a due date is set. |
| **Save changes (n)** / **Discard** | Saves or drops all changed cells at once. Unsaved cells are highlighted, and the count shows at the top. |
| Total, Value | Per row over the months shown; value = quantity × today's price, per currency. Rows without a price say **No price today**. |

Rows appear for each active finished product in each active market it is sold in. A product that does not show needs that market on its **Markets** tab.

### 10.2 Stock

**Planning › Stock** lists stock on hand at the site, grouped by item with released and quarantine totals.

| Field | Effect on planning |
| --- | --- |
| Status: Released | Usable now. |
| Status: Quarantine | Waiting for QC. Not used, unless a plan counts stock waiting for QC; then usable after the item's QC release time. |
| Status: Rejected | Never used. Kept for the record. |
| Quantity | In the item's stock unit. |
| Lot, manufactured, expires | Shown when stock by lot is on. Lots expired by the start of a plan are not used. Lots expiring within 90 days are flagged. |
| Assay, LOD | For assay-compensated materials; reference for dispensing. |
| Stock counted on | The date of your count or warehouse export. Set it whenever you update stock, so everyone knows how current it is. |

An item can have several lines; the same lot can appear once per status. **Add stock line** adds one; click a line to edit or remove it.

### 10.3 Net requirements

**Planning › Net requirements** is a quick check before you plan: what must be made and bought, before any machine time is assigned.

| Control | Effect |
| --- | --- |
| Horizon | Next 30 days, This month, Next month, Next 3 months or Custom dates. Sales plan lines whose due date (or month end) falls inside count. |
| Count stock waiting for QC | Off: only released stock counts. On: quarantine stock counts too, as if QC releases it in time. |

The page shows:

- **Batches to make, Material shortages, Cannot arrive in time, Sales value in horizon** at the top.
- **To make:** each produced item level by level (finished, then semi-finished, then WIP) with sales demand, demand from other products, stock used, net need and the batches. Purple batch chips are full batches; an orange chip is a partial last batch. **Extra** is the output above the need, which goes to stock.
- **Materials and packaging:** required, released and quarantine stock, shortage and the earliest arrival of a new order. **Too late** means it cannot arrive before the end of the horizon. **Quarantine stock would cover it** means switching the option on removes the shortage.

Which stock counts follows the Use stock switches in Company settings, named in the line under the horizon. Expired lots never count, and finished lots too short-dated for every market with demand are shown as "too short-dated". Material quantities include overage and assay compensation ("+0.7 % for lot potency" under the quantity) when those are switched on. The Suggested order column gives the shortage plus the top-up to safety stock, at least the minimum order quantity, with its value when Cost calculation is on.

## 11. Production plans

A plan is the engine's schedule for one site and horizon: which batches to make, on which machines, from when to when. Every plan is kept, so you can make several with different objectives or options and compare them.

### 11.1 How the engine builds a plan

1. It takes the sales plan lines due in the horizon (or, with Sales plan switched off, each market's maximum sellable quantity per month), caps them at the monthly sales limit (when chosen) and rounds them to full shippers (when chosen).
2. It subtracts stock by due date and creates batches level by level through the active BOMs. Each batch knows which delivery or batch it feeds.
3. It places each step on a qualified machine in time, respecting shifts, holidays, downtime, changeovers, campaigns, hold times, QC release and material arrival.
4. When several batches want the same machine, it picks by the objective. It builds up to 40 versions of the schedule and keeps the best for the objective.

A typical plan takes from under a second to a few seconds.

### 11.2 Making a plan

**Planning › Production plans › New plan.**

**Objective**

| Objective | What the engine favours | Choose it when |
| --- | --- | --- |
| On-time delivery (default) | Earliest due date first; fewer changeovers break ties | Customer and tender dates matter most |
| Sales value | Highest-value batches first when they compete; due dates second | Capacity or material is short and you must choose what to serve |
| Utilisation | Grouping similar products to cut changeover and idle time; due dates second | Changeovers are long (swab tests) and dates have slack |

With enough capacity all three often give the same result. They differ when machines or materials are short.

**Horizon and name**

| Field | Effect |
| --- | --- |
| Horizon | Next 30 days, This month, Next month, Next 3 months or Custom, up to 6 months. Demand due inside it is planned; work may run past its end, and the plan warns when it does. |
| Name | Empty = the objective and dates. |
| Start at most (days before needed) | Default 14. The first stage of a chain may not start more than this many days before its batch is needed; later stages follow when their inputs are ready. Empty = start as early as possible, which builds stock months ahead. Lower values keep stock low but leave less buffer. |
| Notes | Shown at the top of the plan. |

**Options**

| Option | On | Off |
| --- | --- | --- |
| Respect material availability (default on) | A batch waits until its missing materials can arrive (lead time + QC). Batches that feed it are also held back, so they are not made too early. | Every material is treated as available: a what-if plan showing what capacity alone allows. |
| Count stock waiting for QC | Quarantine stock, including finished goods, counts once its QC release time has passed. Fewer batches, fewer shortages. | Only released stock counts. |
| Allow release at risk | For items marked **Release at risk**, the next stage starts after the minimum wait without waiting for QC results. Shorter lead times; accepts the risk of a failed result. | The next stage always waits for QC. |
| Cap demand at the sales limit (default on) | Demand above a market's monthly limit is cut to the limit, and the plan lists every cut. | The full sales plan is planned even above the limit. |

**Full shippers only** (default on): each delivery is rounded up to a whole number of shippers, using the product's *Units per shipper*; when that would pass the sales limit it is rounded down instead. The Deliveries tab shows the quantity before rounding and the number of shippers. Off: quantities are planned exactly as requested.

**Make plan** runs the engine and opens the result.

### 11.3 Reading a plan

| Measure | Meaning |
| --- | --- |
| On-time deliveries | Sales plan lines available by their due date, out of all lines in the horizon. Red when any is late or not planned. |
| OTIF (on time in full) | Share of sales plan lines whose whole requested quantity is ready to ship by the due date, with the number of lines and the share of all requested quantity that is ready on time. A line capped at the sales limit or rounded down to full shippers is not in full. |
| Batches scheduled | Batches placed; any not scheduled are counted beneath in red. |
| Changeover time | Cleaning, format change and results waiting across all machines, with the number of changeovers. |
| Sales value on time | Value of on-time deliveries at the plan-date price, of the total value due, per currency. |
| Last batch ends | When the last scheduled step finishes. |

Tabs:

- **Schedule:** one row per machine, grouped by area. Coloured bars are steps, coloured by cleaning group; lighter shades are lower levels (WIP lighter than finished). Grey hatching is cleaning and format change, orange hatching is waiting for results, red hatching is planned downtime. Fridays (non-working days) are shaded. **Month, Week, Day** zoom. Hover a bar for its details; click it to highlight the batch and every batch linked to it, and to open its details below: steps, machines, changeovers, times, what it is made from, what it is used in and which deliveries it serves.
- **Deliveries:** each sales plan line with the **Requested** quantity, the **Planned** quantity (and the cut, if capped or rounded; stock used), the quantity **Ready by due date** with a fill bar and percentage and the late quantity, the batches, when it is available, its status (**On time**, **Late** by hours or days, or **Not planned**) and **OTIF**: **Yes** when the whole request is ready by the due date, **Partial** when only part is, **Short** when it is on time but less than requested, **No** when nothing is ready in time. A total row adds up the quantities when all lines use the same unit.
- **Batches:** batch numbers (B001 onwards, in start order), quantities, start, end and release times. Click one to see it on the schedule.
- **Warnings:** everything the plan could not satisfy (11.4).
- **Machines:** use of each machine in the horizon, production and changeover hours against available hours.

**Export to Excel** saves the plan (with the OTIF scores), batches, machine schedule and deliveries (with on-time quantity, late quantity, fill % and OTIF per line), with your name and the export time.

### 11.4 Warnings

| Warning | Meaning | What to do |
| --- | --- | --- |
| Short by … earliest arrival … | Not enough material; the batch waits for a new delivery | Order now, or plan with **Count stock waiting for QC**, or check the lead time |
| … no lead time recorded | Shortage with no way to tell when material arrives | Enter the item's purchase lead time |
| Held … h before use, limit … h | A batch waited longer than its maximum hold before the next stage | Move or lock the next stage earlier, or review the hold time |
| Requested … planned … (sales limit) | Demand cut to the market's limit | Expected; switch off the cap if the limit is wrong |
| Could not be scheduled: … | Missing BOM, routing or machine, a no-pause step longer than any shift, or an input that failed | Fix the master data named |
| … batches end after the horizon | Work runs past the horizon end | Lengthen the horizon, or add capacity |
| The site has no shifts | Planned around the clock | Set up the working calendar |
| Lock warnings | See section 12 |  |

## 12. Editing, releasing, comparing plans and production orders

Planners refine the engine's schedule by moving and locking batches; the engine re-plans everything else around them. Only **Draft** plans can be changed.

### 12.1 Plan status

| Status | Meaning | Can be changed |
| --- | --- | --- |
| Draft | Working plan | Yes |
| Released | The site's official plan. One per site. Shows who released it and when. | No; **Reopen as draft** first |
| Archived | Kept for reference, hidden from the list unless **Show archived** is on | No; **Restore** first |

**Release** asks for confirmation. Releasing a plan sends any plan released before at that site back to draft.

### 12.2 Moving a batch

1. On a draft plan's **Schedule** tab, press on a bar and drag it.
2. While dragging, rows of machines qualified for that step turn green, others red, and a label shows the new start time.
3. Drop it on the time and machine you want. Dropping on a red row or into the past does nothing.

What happens:

- The whole batch moves so the dragged step starts at the drop time, rounded to 15 minutes and then to the next working time. Its other steps follow in order on their machines; the dragged step uses the machine you dropped it on.
- The batch is **locked** there, drawn with a dashed outline and a lock icon.
- The engine re-plans all unlocked batches around the locked ones with today's sales plan and stock. Unlocked steps fit in the gaps and leave room for the changeover into each locked batch. Batches that feed a locked batch get an earlier deadline so they are ready in time.
- The plan reloads with the moved batch selected. Batch numbers may change, because they follow start order.

### 12.3 Locking, unlocking, re-planning

| Action | Where | Effect |
| --- | --- | --- |
| **Lock in place** | Batch details | Keeps the batch where it is in every later re-plan. Nothing else moves. |
| **Unlock** | Batch details | The engine may move it again; the plan is re-planned at once. |
| **Re-plan** | Plan header | Runs the engine again with today's sales plan and stock, keeping every lock. Use it after the sales plan, stock or master data change. |

The header shows how many batches are locked. Locks are matched by product and batch order. If the sales plan or stock changes so much that a locked batch no longer exists, the lock is dropped and listed in Warnings.

### 12.4 Lock warnings

| Warning | Meaning |
| --- | --- |
| … locked on … at the same time as … | Two locked batches overlap on a machine. Move one. |
| … min short for the changeover before it | The cleaning needed before the locked batch does not fit after the batch before it. Move it later or move the earlier batch. |
| Locked to start … h before … is released | The locked batch starts before its input has finished QC release. Move it later or release the input at risk. |
| A lock … no longer matches a batch | The batch it held is gone after a sales plan or stock change. |

### 12.5 Comparing plans

On **Production plans**, tick the box on two or three plan cards, then **Compare**. The page lines up on-time, late and unplanned deliveries, batches, changeover time and count, sales value on time per currency, last batch end and warnings, with the best value in each row highlighted in green. Below, every delivery shows its status and availability under each plan. Click a plan's name to open it.

### 12.6 Rename, archive, delete

The **…** menu on a plan offers **Rename**, **Archive** or **Restore**, and **Delete plan**. Deleting removes the plan and its schedule; the deletion stays in the audit trail.

### 12.7 Production orders

A released plan issues **manufacturing orders** (raw materials, for dispensing) and **packaging orders** (packaging materials), one per batch. Open the plan and its **Orders** tab.

**Batch numbers.** Plans number batches B001, B002 in start order; production orders need the plant's real batch numbers. Type a number in the **Batch number** box of any batch, or set the site's **Pattern** under **Batch numbers** (for example `{YY}{SEQ:3}` gives 26013, 26014…; `{YYYY}`, `{MM}` and `{CODE}` are also available) with the **Next number**, and click **Fill empty numbers**. Switch on **Restart at 1 every new year** to start again at 1 with the first batch numbered in a new year (26158 is followed by 27001); `{YY}{SEQ:2}` gives 2601, 2602… and `{YY}{SEQ:3}` gives 26001, 26002…. Filling never reuses a number already on this plan or on an order of the site. A number can be changed later; it stays with the batch when the plan is re-planned, and one number cannot be used twice in a plan. A kind of order is made only for batches whose bill of materials has materials of that template's types: filled-capsule or blend batches get manufacturing orders, finished-product batches get packaging orders.

**Creating orders.** Tick batches (one, several, all of a product with the **Product** filter and **Select shown**, or all), then **Create orders** and choose the kinds and templates. Each batch gets one order of each kind whose template lists materials it uses: a blend batch gets a manufacturing order, a packing batch a packaging order. Batches that already have an order of that kind are skipped. Quantities come from the batch's bill-of-materials version and quantity, with overage and assay compensation applied as in the plan.

| Status | Meaning |
| --- | --- |
| Draft | Follows the plan and batch number until it is approved or issued. Prints with a DRAFT mark. Can be deleted. |
| Approved | Every electronic approval level has signed (templates with electronic approval). The content is frozen. |
| Issued | Released to the floor. The content is frozen; the file always prints the same. |
| Cancelled | Kept with its reason; prints with a CANCELLED mark. |

**Signing and issuing.** With electronic approval on, select orders and click **Sign**, choose the meaning and enter your password: your signature fills the next open level of each order, with your name and the time. Levels sign in order and by different people; a wrong password signs nothing and is recorded. When all levels have signed the order is **Approved**, and **Issue** releases it. Without electronic approval, **Issue** releases drafts directly and people sign the printed boxes.

**Changes after issue.** If a batch number changes after an order was issued, the order shows a warning. **Reissue** cancels it with your reason and makes a new draft as the next revision (printed at the bottom). **Cancel orders** also asks for a reason.

**Files.** **Download PDF** and **Download Word** produce one file for all selected orders, each starting on a new page with its own page count. Every download is recorded in the audit trail.

**Templates** (Company settings › **Production orders**, administrators): one per kind, with the title, **Format number** (printed on every page), page orientation, logo, footer note, the **Number pattern** for order numbers (`{BATCH}`, `{YY}`, `{MM}`, `{DD}`, `{CODE}`, `{SEQ:4}`), the header fields and their labels and order, how many fields per row, the material table columns and their labels and order, which material types are listed, the approval levels and their titles, **Electronic approval in Complanning**, and the remarks heading and blank lines. **Preview** shows a sample order with the template as edited. Orders keep the layout they were approved or issued with.

## 13. Excel import and export, and sample data

### 13.1 Excel import

The **Excel** button on Items and materials, Machines, Sales plan and Stock offers **Download template**, an import and an export. Start from the template: its first sheet has the right columns, its **How to fill** sheet explains each one, and columns marked \* are required.

Import always runs in two steps: **Check file** shows how many rows will be created, updated or replaced and lists every row with a problem; **Import n rows** saves. Nothing is saved while any row has a problem, so a file never half-loads.

| Import | Rows matched by | Notes |
| --- | --- | --- |
| Items | Item code | New codes are created, existing ones updated. Type and stock unit of existing items cannot change by import. |
| Machines | Machine code, at the selected site | New codes created, existing updated. |
| Sales plan | Product, market and month | A quantity of 0 removes that month. The product must be sold in the market. Due dates must fall in the month. |
| Stock | Not matched: replaces | The file replaces all stock lines of the site, and the stock date becomes today. Statuses are Released, Quarantine or Rejected. |

Files must be .xlsx and at most 5 MB. Every import is recorded in the audit trail.

### 13.2 Excel export

| Export | Where | Contents |
| --- | --- | --- |
| All master data | Items and materials › Excel | Items, units, pack conversions, markets and prices, bills of materials, and the selected site's machines and routings |
| Sales plan | Sales plan › Excel | Every line with today's price and value; can be edited and imported back |
| Stock | Stock › Excel | Every line; can be edited and imported back |
| Plan | Plan › Export to Excel | Summary, batches, machine schedule and deliveries, in the site's time zone |
| Audit trail | Audit trail › Export | Filtered entries, as Excel or CSV |

Every Excel export carries an **Export info** sheet with the user's name and email, the export time in UTC and the company. Every export is recorded in the audit trail.

### 13.3 Sample data

The sample is a small pharmaceutical plant for training and testing: paracetamol 500 mg tablets for Egypt and Saudi Arabia, and vitamin C syrup for Egypt.

| Button | Who, when | Adds |
| --- | --- | --- |
| **Load sample data** (Items page) | Company administrator, company with no items yet | 36 items, 7 bills of materials over three levels, 20 machines with routings and downtime, markets with price history, a calendar with Ramadan shifts and holidays, rules, six months of sales plan and stock, at the first site |
| **Load sample rules** (Changeovers) | Company administrator, site with sample products and no rules | Cleaning groups, changeovers, campaigns, hold times, holding and QC times |
| **Load sample sales plan and stock** (Sales plan or Stock) | Company administrator, site with sample products and neither a sales plan nor stock | Six months of sales plan from the current month and a stock snapshot |

The sample stock is deliberately short of four materials, so plans show shortage warnings. Load the sample into a test company, not your live one: sample records are real records in the audit trail.

## 14. Audit trail and 21 CFR Part 11 controls

The database records every change to data, every sign-in and every export, and nobody, administrators included, can edit or delete an entry.

### 14.1 Using the audit trail

**Administration › Audit trail** (company and platform administrators).

| Control | Effect |
| --- | --- |
| From, To | Date range, in your company's time zone. |
| User, Action, Record type, search | Narrow the list; **Clear filters** resets them. |
| A row | Time, user, action, record type and record, with the fields changed. Open it for each field's value before and after. |
| **Export** | Excel or CSV of the filtered entries, stamped with your name and the time. The export is itself recorded. |

| Action | Recorded when |
| --- | --- |
| INSERT, UPDATE, DELETE | A record is created, changed or removed: who, when, old and new values |
| LOGIN, LOGIN\_FAILED, LOGOUT, SESSION\_TIMEOUT | Sign-in events |
| LOCKED, UNLOCKED | An account locks after failed attempts, or an administrator unlocks it |
| PASSWORD\_CHANGED, PASSWORD\_RESET | A user changes a password, or an administrator resets one |
| IMPORT, EXPORT | An Excel import is saved, or any export is downloaded |
| SAMPLE\_DATA, BOOTSTRAP | Sample data is loaded, or the platform administrator is created at installation |

For plans, the audit trail records each plan's creation, name, status, release, locks and deletion. The generated batches and operations are not listed one by one; the plan row and its locks show every manual change.

A change needs no reason in this version, as agreed for an advisory planning tool.

### 14.2 Controls in Complanning

| Requirement | How Complanning meets it |
| --- | --- |
| Unique user identity | One account per person, by email; users are disabled, never deleted |
| Password controls | Length, character rules, expiry, history (section 5.4) |
| Protection against guessing | Lockout after failed attempts |
| Unattended sessions | Automatic sign-out after inactivity |
| Authority checks | Roles per site; edit rights checked on the server for every change |
| Audit trail | Database-enforced, append-only, with old and new values |
| Records copies | Exports with user name and time; audit export in Excel or CSV |
| Data separation | Each company's data is isolated by the database; the platform administrator cannot read it |

Electronic signatures and an approval workflow are not part of this version. Complanning is a planning aid: the validation of the system for your use, and of the master data entered, remains your company's responsibility.

## 15. Monthly routine, troubleshooting and glossary

### 15.1 A monthly planning routine

1. **Update the sales plan** for the coming months, with due dates for tenders and export orders (Sales plan, or import from Excel).
2. **Update stock** from the warehouse and set **Stock counted on** (Stock, or import from Excel, which replaces the site's stock).
3. **Check the calendar:** confirm estimated holidays, add planned downtime, add a period for Ramadan if it falls in the horizon.
4. **Check net requirements** for the horizon. Order materials that are short, and note any marked **Too late**.
5. **Make a plan** with the On-time delivery objective. If deliveries are late, make a second with Sales value or Utilisation, or with different options.
6. **Compare** the plans and pick one.
7. **Adjust:** drag batches to where production needs them, lock what is agreed, and **Re-plan**.
8. **Release** the plan and **Export to Excel** for the production meeting.
9. During the month, after big changes to demand, stock or machines, **Reopen as draft**, **Re-plan**, and release again.

### 15.2 Troubleshooting

| Problem | Likely cause | Fix |
| --- | --- | --- |
| A product is missing from the sales plan | Not sold in any active market, or inactive | Add the market on the product's Markets tab |
| A product's batches are not scheduled | No active BOM, no routing at this site, or no active machine on a step | Activate a BOM, add a routing, or qualify a machine |
| A no-pause step is never scheduled | It is longer than any unbroken working block | Add a back-to-back shift, or switch off No pause |
| Everything is late | Missing materials with long lead times | Plan with Respect material availability off to see capacity alone; order materials |
| Too much stock is built early | Start at most is empty or large | Set Start at most to 7–14 days |
| Very long changeovers | Group-to-group swab rules between groups sharing a machine | Make a Utilisation plan, or add product-pair rules where cleaning is shorter |
| Work on a holiday | The holiday is estimated, not confirmed | Confirm it on the Working calendar, then re-plan |
| Cannot drag a bar | The plan is released or archived, or you are not a planner at this site | Reopen as draft, or ask an administrator for the planner role |
| Conversion error when saving a BOM | Mixing kg and L without density, or a count unit without a pack conversion | Add the item's density or pack conversion |
| Signed out unexpectedly | Session timeout after inactivity | Sign in again; save more often |

### 15.3 Glossary

| Term | Meaning |
| --- | --- |
| Batch | One production run of a produced item, sized by its BOM |
| BOM | Bill of materials: components and quantities for one batch |
| Campaign | Consecutive batches of the same product on a machine |
| Changeover | Machine time between batches: cleaning, format change, waiting for results |
| Cleaning group | Products that share changeover rules |
| Clean hold, Dirty hold | How long a machine may stay idle after cleaning, or before cleaning |
| Horizon | The date range a plan or net requirement covers |
| Lock | A batch fixed in time and machine; re-planning works around it |
| LOD | Loss on drying, the water content of a lot |
| Max hold, Min wait | Longest and shortest time between the end of a batch and the start of the next stage |
| Net requirement | What must still be made or bought after stock is subtracted |
| Overage | A registered excess added to a BOM line |
| Pegging | The link from a batch to the batch or delivery it supplies |
| Quarantine | Stock waiting for QC results |
| Release at risk | Starting the next stage before QC results |
| Routing | The steps and machines that make one batch at a site |
| Yield | The share of the nominal batch size expected as good output |
