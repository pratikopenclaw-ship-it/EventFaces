# Legal texts: review checklist for counsel

EventFaces ships four legal documents, written for how the service actually works, in German (binding) and English:

| Document | Web | iOS app | Source |
|---|---|---|---|
| Terms of Use (Nutzungsbedingungen) | `/terms` | Sign-in, Settings › About | `backend/app/services/legal.py` |
| Organizer Terms incl. data processing agreement (Art. 28 GDPR) | `/organizer-terms` | Settings › About, acceptance sheet | same |
| Privacy Notice (Datenschutzerklärung), incl. a cookie section | `/privacy` | Settings › About, sign-in | same |
| Impressum (§ 5 DDG) | `/imprint` | Settings › About | same |

**These are drafts by the engineering team, not legal advice.** A lawyer (German IT and data protection law) must review them before launch. The engineering side is in place, so changes are cheap:
- versioned texts;
- recorded acceptance;
- re-acceptance on change;
- a production guard against missing operator details.

## 1. Fill in the operator's identity (blocking)

Production refuses to start while these are empty (`Settings` validator). Set them in `.env.prod`:

| Variable | Content |
|---|---|
| `LEGAL_OPERATOR_NAME` | Legal name incl. legal form (e.g. "Example Photos GmbH") |
| `LEGAL_OPERATOR_ADDRESS` | Postal address for service (no P.O. box); lines separated by `\n` |
| `LEGAL_REPRESENTATIVE` | Managing director(s) / owner; also "responsible for content" under § 18(2) MStV |
| `LEGAL_EMAIL` | Contact email, also the DSA single point of contact |
| `LEGAL_PHONE` | Phone (second rapid contact channel) |
| `LEGAL_DPO_CONTACT` | Data protection officer (likely mandatory: large-scale biometric processing, Art. 37(1)(c) GDPR) |
| `LEGAL_SUPERVISORY_AUTHORITY` | The authority competent for the operator's seat (state DPA) |
| `LEGAL_EMAIL_PROVIDER` | The email delivery processor |
| `LEGAL_REGISTER`, `LEGAL_VAT_ID` | Optional (omitted when empty, e.g. for sole proprietors) |
| `LEGAL_HOSTING_PROVIDER`, `LEGAL_STORAGE_PROVIDER` | Defaults: Hetzner (Germany), Cloudflare R2 (EU jurisdiction); change if different |

## 2. Points for counsel to decide or confirm

**Biometric data (highest risk)**
1. **Face templates of everyone in event photos.** The Organizer Terms make the organizer the controller and require a legal basis, usually explicit consent of the people photographed (Art. 9(2)(a)), with an easy opt-out. Counsel should decide:
   - whether this is workable for the target events;
   - whether a joint-controller arrangement (Art. 26) is more accurate.
2. **DPIA (Art. 35):** required before launch (also in DEPLOYMENT.md).
3. **Attendee consent text** (`services/consent_text.py`): review it with these documents. It is versioned separately.

**Contract and consumer law**

4. **Inclusion of the Terms (§ 305(2) BGB):** every account creation has an unticked checkbox, "I accept the Terms of Use and confirm that I am at least 16". The record kept is document, version, time, language and channel (`legal_acceptances`). Changed Terms are accepted again before further use. Please confirm this is sufficient, and whether the record should be kept after account deletion for evidence (Art. 17(3)(e)). Today it is deleted with the account.
5. **Liability clauses** (sections 12 Terms / 9 Organizer Terms): standard BGB-compliant structure. Please check them against §§ 307–309 BGB, and check the B2B cap (fees of the last 12 months).
6. **Paid organizer services:**
   - The contract is concluded by individual order (offer and acceptance in text form).
   - Payment and invoicing are not built.
   - Confirm the order process, price list, invoicing and **retention duties** (HGB/AO, 10 years for invoices).
7. **Consumer organizers** (private hosts): the withdrawal information (section 11 Organizer Terms) follows the statutory model. Please verify the wording, and add the model withdrawal form (Anlage 2 EGBGB) to order confirmations.
8. **Minimum age 16** (owner decision): users confirm it at sign-up. There is no age verification beyond that.
9. **Consumer arbitration (§ 36 VSBG):** the texts state "not willing and not obliged". Please confirm, and also whether the operator is above the 10-employee threshold. The EU ODR platform was discontinued on 20 July 2025, so no ODR link is included.

**Digital Services Act / platform duties**

10. Hosting service with user uploads:
    - notice and action exists: Report, Request removal and email;
    - statement of reasons on restrictions;
    - single point of contact (Art. 11, 12) = `LEGAL_EMAIL`.

    Please confirm the processes behind them, including handling times and records.

**Privacy notice facts to verify operationally** (we wrote them; the operator must make them true)

11. Server logs deleted after **at most 14 days**: configure log rotation on the host and Caddy.
12. Photos deleted **at the latest 30 days** after contract end, and removed from **backups within a further 30 days** (DPA section 9): align with the backup schedule.
13. DPAs signed with every processor (hosting, storage, email). Transfers to the US rely on the EU-US Data Privacy Framework or SCCs (Apple, Google, Cloudflare).
14. **No cookie banner:** the site sets only strictly necessary first-party cookies (`ef_access`, `ef_refresh`, `ef_csrf`, `ef_theme`; § 25(2) no. 2 TDDDG). A test fails if the code ever sets a cookie the notice doesn't list. Adding analytics, ads or third-party embeds would require consent and a banner.

**App Store**

15. Apple's standard EULA applies unless a custom EULA is uploaded. Ours are platform terms, which Apple permits alongside it. Link the Terms and the Privacy Notice in App Store Connect (`ios/APP_STORE.md`).

## 3. How to change a text

1. Edit `backend/app/services/legal.py`, in both languages and with the same structure (a test checks it).
2. Bump `VERSIONS[...]` to the new date. `tests/test_legal.py` fails until the version and its pinned hash are updated, so a changed text can never keep an old version.
3. Deploy. For the Terms and the Organizer Terms, every user is asked to accept the new version, on web and in the app, before further use. Account settings, deletion and consent withdrawal stay available without accepting.
