import { serve } from "https://deno.land/std@0.208.0/http/server.ts";

serve(() => new Response("✅ Deno Deploy is LIVE!", { status: 200 }));
