// Optional bindings & runtime secrets configured via `wrangler secret put` (not stored in wrangler.jsonc).
interface Env {
  ARTIFACTS?: R2Bucket;
  PUBLISH_API_TOKEN?: string;
}
