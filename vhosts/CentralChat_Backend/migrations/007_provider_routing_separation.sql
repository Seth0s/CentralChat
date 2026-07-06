-- Migration: Remove provider routing from tier profiles (moved to user_preferences)
-- Date: 2026-06-07
-- Reason: Provider routing (sort/order) is a user preference, not a tier property.
-- User now has "provider_routing" key in user_preferences (cheapest/fastest/highest_throughput).

ALTER TABLE IF EXISTS user_tier_profiles
    DROP COLUMN IF EXISTS sort,
    DROP COLUMN IF EXISTS order_providers,
    DROP COLUMN IF EXISTS ignore_providers,
    DROP COLUMN IF EXISTS allow_fallbacks;
