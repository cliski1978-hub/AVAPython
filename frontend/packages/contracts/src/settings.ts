import type { ContractVersion } from "./version";
import type { ModelCapabilities } from "./models";
import type { ModelHostingMode } from "./runs";

/**
 * Persisted configuration contracts for the Settings API.
 *
 * These mirror the backend `/settings/*` wire contracts exactly. They are
 * configuration, not discovery: `/model-providers`, `/models`, and `/runtimes`
 * continue to report what is currently available, and the two concepts are
 * never merged.
 *
 * Security note: `credential_reference` names where AVA resolves a secret and
 * is safe to read and display. Resolved secret material is never part of any
 * contract here and must never be added to one — a client cannot render a value
 * it is not allowed to receive.
 */

/** One configured provider connection as persisted. */
export interface ProviderConnectionResponse {
  provider_connection_id: string;
  provider_id: string;
  display_name: string;
  endpoint: string | null;
  enabled: boolean;
  /** Opaque location such as `env:OPENAI_API_KEY`. Never the secret itself. */
  credential_reference: string | null;
  contract_version: ContractVersion;
}

/** Every configured provider connection, including disabled ones. */
export interface ProviderConnectionListResponse {
  provider_connections: ProviderConnectionResponse[];
  contract_version: ContractVersion;
}

/** Payload for POST /settings/providers. `endpoint`/`credential_reference` are optional. */
export interface CreateProviderConnectionRequest {
  provider_connection_id: string;
  provider_id: string;
  display_name: string;
  endpoint?: string | null;
  enabled?: boolean;
  credential_reference?: string | null;
}

/**
 * Payload for PUT /settings/providers/{provider_connection_id}.
 *
 * A full replacement of the mutable fields: send an explicit `null` to clear
 * `endpoint` or `credential_reference`. `provider_id` is optional and not a way
 * to reassign a connection — omit it, or resend the current value; any other
 * value is rejected with a conflict.
 */
export interface UpdateProviderConnectionRequest {
  display_name: string;
  endpoint: string | null;
  enabled: boolean;
  credential_reference: string | null;
  provider_id?: string | null;
}

/** One configured model as persisted (declared configuration, not discovery). */
export interface ModelConfigurationResponse {
  model_id: string;
  provider_connection_id: string;
  provider_model_name: string;
  display_name: string;
  hosting_mode: ModelHostingMode;
  capabilities: ModelCapabilities;
  enabled: boolean;
  contract_version: ContractVersion;
}

/** Every configured model, including disabled ones. */
export interface ModelConfigurationListResponse {
  models: ModelConfigurationResponse[];
  contract_version: ContractVersion;
}

/** Payload for POST /settings/models; the provider connection must already exist. */
export interface CreateModelConfigurationRequest {
  model_id: string;
  provider_connection_id: string;
  provider_model_name: string;
  display_name: string;
  hosting_mode: ModelHostingMode;
  capabilities?: ModelCapabilities;
  enabled?: boolean;
}

/**
 * Payload for PUT /settings/models/{model_id}.
 *
 * `provider_connection_id` is optional and not a way to reassign a model: omit
 * it, or resend the current value; any other value is rejected with a conflict.
 */
export interface UpdateModelConfigurationRequest {
  provider_model_name: string;
  display_name: string;
  hosting_mode: ModelHostingMode;
  capabilities: ModelCapabilities;
  enabled: boolean;
  provider_connection_id?: string | null;
}

/** One configured runtime instance: configuration identity and adapter kind only. */
export interface RuntimeConfigurationResponse {
  runtime_configuration_id: string;
  runtime_type: string;
  display_name: string;
  enabled: boolean;
  contract_version: ContractVersion;
}

/** Every configured runtime, including disabled ones. */
export interface RuntimeConfigurationListResponse {
  runtimes: RuntimeConfigurationResponse[];
  contract_version: ContractVersion;
}

/**
 * Payload for POST /settings/runtimes.
 *
 * `runtime_type` is an opaque adapter kind and is not validated against
 * installed runtimes.
 */
export interface CreateRuntimeConfigurationRequest {
  runtime_configuration_id: string;
  runtime_type: string;
  display_name: string;
  enabled?: boolean;
}

/**
 * Payload for PUT /settings/runtimes/{runtime_configuration_id}.
 *
 * `runtime_type` is optional and not a way to retype a runtime: omit it, or
 * resend the current value; any other value is rejected with a conflict.
 */
export interface UpdateRuntimeConfigurationRequest {
  display_name: string;
  enabled: boolean;
  runtime_type?: string | null;
}

/** The application's single set of default execution references. */
export interface ApplicationExecutionDefaultsResponse {
  default_provider_connection_id: string;
  default_model_id: string;
  default_runtime_configuration_id: string;
  contract_version: ContractVersion;
}

/**
 * Current defaults plus an explicit configured flag. "Not configured yet" is
 * normal application state, not a 404, so a settings screen can render it
 * without treating a missing resource as a failure.
 */
export interface ApplicationExecutionDefaultsState {
  configured: boolean;
  defaults: ApplicationExecutionDefaultsResponse | null;
  contract_version: ContractVersion;
}

/** Payload for PUT /settings/defaults; full replacement of the one record. */
export interface SetApplicationExecutionDefaultsRequest {
  default_provider_connection_id: string;
  default_model_id: string;
  default_runtime_configuration_id: string;
}
