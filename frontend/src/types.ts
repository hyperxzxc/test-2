export interface Reference {
  id: number;
  name?: string;
  domain?: string;
  state?: string;
}
export interface References {
  domains: Reference[];
  groups: Reference[];
  sources: Reference[];
  countries: { code: string; name: string }[];
}
export interface Meta {
  configured: boolean;
  demo_mode: boolean;
  defaults: {
    domain_id: number | null;
    group_id: number | null;
    traffic_source_id: number | null;
  };
}
export interface Binding {
  offer_id: number;
  name: string;
  share: number;
  pinned: boolean;
  removed: boolean;
  state: "active" | "disabled";
}
export interface Stream {
  stream_id: number;
  campaign_id: number;
  name: string;
  type: string;
  version: number;
  dirty: boolean;
  bindings: Binding[];
  synced_at: string;
  editable: boolean;
  deleted: boolean;
  pending_operation_id: string | null;
}
export interface Step {
  name: string;
  status: string;
  attempts: number;
  error: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}
export interface Operation {
  id: string;
  kind: string;
  status: string;
  campaign_id: number | null;
  stream_id: number | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  result: {
    campaign_id?: number;
    stream_id?: number;
    alias?: string;
    stream_ids?: number[];
  } | null;
  steps: Step[];
}
export interface Campaign extends Reference {
  alias?: string;
}
export interface CreateRequest {
  name: string;
  country: string;
  offer_id: number;
  domain_id: number;
  group_id: number;
  traffic_source_id: number;
}
export interface EditAction {
  action: "add" | "remove" | "restore" | "pin" | "unpin" | "set_share";
  offer_id: number;
  share?: number;
}
