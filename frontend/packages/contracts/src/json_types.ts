/** Shared AVA JSON-safe value types.
 *
 * All AVA contract fields that carry arbitrary JSON should use this type so
 * non-serializable values are excluded at the type level.
 */

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };