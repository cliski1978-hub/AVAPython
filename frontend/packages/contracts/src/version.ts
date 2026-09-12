/** AVA contract versioning.
 *
 * Every public contract payload carries a contract version. Start at v1.
 * Versioning prefers additive changes over breaking changes.
 */

export const CONTRACT_VERSION = "v1" as const;

/**
 * The exact contract version supported by this package. Every public
 * contract payload carries a version typed as this const.
 */
export type ContractVersion = typeof CONTRACT_VERSION;