import type { ThemePref } from "@/lib/theme";

export type UserRole = "super_admin" | "organizer" | "attendee";
export type JoinMode = "code" | "invite";
export type ModerationMode = "auto" | "manual";
export type MemberRole = "organizer" | "attendee";
export type MemberStatus = "pending" | "approved" | "revoked";

export interface User {
  id: string;
  email: string;
  role: UserRole;
  email_verified_at: string | null;
  created_at: string;
  theme: ThemePref;
}

export interface EventPublic {
  id: string;
  slug: string;
  name: string;
  date: string | null;
  description: string;
  access_expires_at: string | null;
  guest_upload_enabled: boolean;
  allow_selfie_file_upload: boolean;
  /** Organizer's brand colour (#rrggbb), or null for the default accent. */
  accent_color: string | null;
  has_logo: boolean;
}

export interface EventListItem extends EventPublic {
  my_role: MemberRole | null;
  can_manage: boolean;
  photo_count: number;
  /** The caller's queued ("we'll notify you") search for this event, if any. */
  search_state?: SearchState | null;
}

export interface EventAdmin extends EventPublic {
  join_mode: JoinMode;
  access_code: string;
  moderation_mode: ModerationMode;
  delete_photos_on_expiry: boolean;
  drive_folder_id: string | null;
  created_at: string;
}

export interface EventInput {
  name: string;
  date: string | null;
  description: string;
  join_mode: JoinMode;
  access_expires_at: string | null;
  guest_upload_enabled: boolean;
  moderation_mode: ModerationMode;
  allow_selfie_file_upload: boolean;
  delete_photos_on_expiry: boolean;
  drive_folder: string | null;
  accent_color: string | null;
}

export interface JoinPreview {
  slug: string;
  name: string;
  date: string | null;
  join_mode: JoinMode;
}

export interface Member {
  user_id: string;
  email: string;
  role: MemberRole;
  status: MemberStatus;
  joined_at: string;
  expires_at: string | null;
}

export type SyncRunStatus = "queued" | "running" | "completed" | "failed";
export type IndexStatus = "queued" | "importing" | "indexing" | "indexed" | "failed";
export type PhotoStatus = "processing" | "published" | "pending_review" | "rejected" | "removed";

export interface SyncRun {
  id: string;
  status: SyncRunStatus;
  folder_id: string;
  files_listed: number;
  files_new: number;
  files_retried: number;
  files_over_limit: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface SyncStatus {
  drive_configured: boolean;
  service_account_email: string | null;
  folder_id: string | null;
  last_run: SyncRun | null;
  in_progress: boolean;
  pipeline: Record<IndexStatus, number>;
  published_photos: number;
  faces: number;
}

export interface PhotoAdmin {
  id: string;
  source: "drive" | "guest";
  status: PhotoStatus;
  index_status: IndexStatus;
  original_filename: string | null;
  width: number | null;
  height: number | null;
  face_count: number;
  error: string | null;
  created_at: string;
}

export interface PhotoPage {
  items: PhotoAdmin[];
  total: number;
}

export interface ConsentSection {
  heading: string;
  paragraphs: string[];
}

/** The versioned consent text, from the API in the user's language (shared with the iOS app). */
export interface ConsentText {
  locale: string;
  title: string;
  intro: string;
  sections: ConsentSection[];
  agreement: string;
  action: string;
}

export interface ConsentInfo {
  version: string;
  grant_days: number;
  given: boolean;
  given_at: string | null;
  text: ConsentText;
}

export type Tier = "best" | "possible";
export type Verdict = "me" | "not_me";

export interface MatchedPhoto {
  id: string;
  width: number | null;
  height: number | null;
  similarity: number | null;
  tier: Tier | null; // null for the user's own uploads
  verdict: Verdict | null;
}

export interface SearchResult {
  search_id: number;
  matches: MatchedPhoto[];
  quality: { shot: string; score: number }[];
}

export interface DownloadTicket {
  url: string;
  expires_in: number;
  count: number;
}

export interface UploadStart {
  photo_id: string;
  upload_url: string;
  content_type: string;
  expires_in: number;
}

export interface MyUpload {
  id: string;
  original_filename: string | null;
  status: PhotoStatus;
  index_status: IndexStatus;
  error: string | null;
  created_at: string;
}

export interface ModerationItem {
  id: string;
  original_filename: string | null;
  uploader_email: string | null;
  index_status: IndexStatus;
  face_count: number;
  created_at: string;
}

export type ReportReason = "inappropriate" | "its_me_remove" | "privacy" | "other";

export interface PhotoReport {
  id: string;
  photo_id: string;
  reason: ReportReason;
  details: string;
  status: "open" | "dismissed" | "photo_removed";
  reporter_email: string | null;
  created_at: string;
}

export type InviteStatus = "pending" | "accepted" | "revoked";

export interface Invite {
  id: string;
  email: string;
  status: InviteStatus;
  sent_at: string | null;
  expires_at: string;
  accepted_at: string | null;
}

export interface InviteUploadResult {
  sent: string[];
  invalid: string[];
  already_members: string[];
  already_accepted: string[];
}

export interface InvitePreview {
  event_name: string;
  event_date: string | null;
  email: string;
  account_exists: boolean;
  accepted: boolean;
}

export interface RemovalRequestItem {
  id: string;
  email: string;
  message: string;
  status: "unverified" | "submitted" | "resolved" | "declined";
  matched_photo_ids: string[];
  created_at: string;
}

export interface SearchLogRow {
  user_email: string | null;
  match_count: number;
  created_at: string;
}

export interface QualityBand {
  lower: number;
  upper: number;
  me: number;
  not_me: number;
  wrong_rate: number | null;
}

export interface MatchQuality {
  searches: number;
  feedback: number;
  missing_reports: number;
  bands: QualityBand[];
  current_possible: number;
  current_best: number;
  suggested_threshold: number | null;
  suggestion_note: string;
  quality_histogram: number[];
  rejection_reasons: Record<string, number>;
  shots_total: number;
  shots_passed: number;
}

export interface GlobalMatchQuality extends MatchQuality {
  events: { event_id: string; event_name: string; searches: number; feedback: number; wrong_rate: number | null; missing_reports: number }[];
}

/** A search accepted while the service was busy: results arrive later (email + event page). */
export interface QueuedSearch {
  queued: true;
  detail: string;
  expires_in: number;
}

export type SearchState = "none" | "queued" | "done" | "rejected" | "cancelled" | "expired";

export interface SearchStatus {
  state: SearchState;
  match_count: number | null;
  message: string | null;
  shot: string | null;
}

// --- Billing (services/billing on the API) ---

export type PlanKey = "event_s" | "event_m" | "event_l" | "pro";

export interface Plan {
  key: PlanKey;
  name: string;
  kind: "one_off" | "subscription";
  price_cents: number;
  max_attendees: number;
  max_photos: number;
  events_per_period: number;
}

export interface PriceList {
  currency: string;
  vat_rate: number;
  vat_included: boolean;
  example_prices: boolean;
  test_mode: boolean;
  plans: Plan[];
}

export type OrderStatus = "pending" | "paid" | "canceled";

export interface Order {
  id: string;
  plan: string;
  plan_name: string;
  kind: "one_off" | "subscription" | "allowance";
  amount_cents: number;
  vat_cents: number;
  currency: string;
  vat_rate: number;
  status: OrderStatus;
  failure_code: string | null;
  event_name: string | null;
  event_date: string | null;
  event_id: string | null;
  created_at: string;
  paid_at: string | null;
}

export interface Subscription {
  id: string;
  plan: string;
  plan_name: string;
  status: "active" | "expired";
  current_period_start: string;
  current_period_end: string;
  canceled_at: string | null;
  events_included: number;
  events_used: number;
}

export interface BillingOverview {
  subscription: Subscription | null;
  orders: Order[];
}

export interface TestCheckout {
  order: Order;
  test_cards: string[];
}

export interface TestPaymentResult {
  outcome: "paid" | "failed" | "duplicate" | "ignored";
  order: Order;
}

export interface EventUsage {
  plan: string | null;
  plan_name: string | null;
  max_attendees: number | null;
  max_photos: number | null;
  attendees: number;
  photos: number;
}
