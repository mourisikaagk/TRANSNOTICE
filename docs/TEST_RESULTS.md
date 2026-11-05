# Test results

Actual output of `python -m pytest -v` for version 2.1, run by the author of this code in the build environment.

| Item | Value |
|---|---|
| Date | 2026-10-29 |
| OS | Linux (Ubuntu 24) |
| Python | 3.12.3 |
| Flask / requests / beautifulsoup4 / pytest | 3.1.3 / 2.33.1 / 4.14.3 / 9.1.1 |

Also checked by hand: upgrading a real version 1 database (6 notices, 6 revisions) with the version 2 code kept all data, added coordinates, and created no extra revisions; every page and static file returned HTTP 200 from a running server; the three JavaScript files pass `node --check`.

**Not verified:** a run on Windows or Python 3.10/3.11; clicking through the pages in a real browser (theme toggle, follow buttons, map drawing, weather panel and layout were not seen on screen); live Open-Meteo or OpenStreetMap access (the build environment has no access, so those paths were tested with mocked responses); real SMTP; any live transport source; deployment. Run the tests on your own machine and replace this file with your own output before submitting.

```
tests/test_accounts.py::test_signup_creates_session_and_hashes_password PASSED
tests/test_accounts.py::test_signup_validation PASSED
tests/test_accounts.py::test_duplicate_email_is_rejected_case_insensitively PASSED
tests/test_accounts.py::test_login_logout_and_session_rotation PASSED
tests/test_accounts.py::test_wrong_password_and_unknown_user_get_the_same_message PASSED
tests/test_accounts.py::test_login_is_throttled_after_repeated_failures PASSED
tests/test_accounts.py::test_account_forms_need_csrf PASSED
tests/test_accounts.py::test_follow_creates_one_subscription_and_unfollow_removes_it PASSED
tests/test_accounts.py::test_my_routes_api_rules PASSED
tests/test_accounts.py::test_alert_inbox_records_each_change_once PASSED
tests/test_accounts.py::test_delete_account_removes_all_user_data PASSED
tests/test_accounts.py::test_admin_flag_survives_user_login_but_user_is_not_admin PASSED
tests/test_change_detection.py::test_hash_ignores_route_order_and_whitespace PASSED
tests/test_change_detection.py::test_hash_changes_on_any_tracked_field PASSED
tests/test_change_detection.py::test_extension_and_shortening PASSED
tests/test_change_detection.py::test_end_date_added_and_removed PASSED
tests/test_change_detection.py::test_route_changes_described PASSED
tests/test_change_detection.py::test_withdrawn_takes_priority_and_summary_edit PASSED
tests/test_change_detection.py::test_identical_content_has_no_changes PASSED
tests/test_collector.py::test_first_run_collects_demo_notices PASSED
tests/test_collector.py::test_repeated_runs_create_no_duplicates_or_alerts PASSED
tests/test_collector.py::test_mentor_extends_outage_by_24_hours PASSED
tests/test_collector.py::test_advisory_without_end_date_does_not_crash PASSED
tests/test_collector.py::test_failed_fetch_does_not_refresh_old_data PASSED
tests/test_collector.py::test_old_notices_become_stale_not_live PASSED
tests/test_collector.py::test_empty_result_is_treated_as_failure_not_mass_withdrawal PASSED
tests/test_collector.py::test_withdraw_scenario_and_expiry_event_logged_once PASSED
tests/test_collector.py::test_unexpected_exception_is_recorded_not_raised PASSED
tests/test_collector.py::test_unapproved_live_source_is_not_enabled PASSED
tests/test_database.py::test_migrations_are_idempotent_and_match_schema_file PASSED
tests/test_database.py::test_duplicate_notices_are_prevented PASSED
tests/test_database.py::test_multiple_routes_stored_and_filterable PASSED
tests/test_database.py::test_missing_end_date_is_stored_as_null_and_stays_active PASSED
tests/test_database.py::test_expired_and_upcoming_status PASSED
tests/test_database.py::test_extension_updates_same_notice_and_keeps_history PASSED
tests/test_database.py::test_route_association_change_creates_revision PASSED
tests/test_database.py::test_explicit_withdrawal_and_reinstatement PASSED
tests/test_database.py::test_notice_missing_from_complete_listing_is_withdrawn PASSED
tests/test_database.py::test_partial_listing_never_withdraws PASSED
tests/test_database.py::test_expired_notice_missing_from_source_is_not_withdrawn PASSED
tests/test_database.py::test_unchanged_notice_only_refreshes_confirmation_time PASSED
tests/test_database.py::test_foreign_keys_enforced PASSED
tests/test_database.py::test_upgrade_from_version_1_keeps_existing_data PASSED
tests/test_fetcher.py::test_success_first_try PASSED
tests/test_fetcher.py::test_retries_with_exponential_backoff_then_succeeds PASSED
tests/test_fetcher.py::test_gives_up_after_retry_ceiling PASSED
tests/test_fetcher.py::test_client_errors_are_not_retried PASSED
tests/test_fetcher.py::test_robots_disallow_blocks_fetch PASSED
tests/test_fetcher.py::test_unreadable_robots_is_treated_as_disallow PASSED
tests/test_fetcher.py::test_rejects_non_http_urls PASSED
tests/test_fetcher.py::test_rate_limit_waits_between_requests PASSED
tests/test_map_weather.py::test_coordinates_parsed_and_invalid_ones_ignored PASSED
tests/test_map_weather.py::test_location_updates_silently_without_a_revision PASSED
tests/test_map_weather.py::test_map_api_returns_only_located_notices PASSED
tests/test_map_weather.py::test_notice_without_coordinates_gets_no_pin PASSED
tests/test_map_weather.py::test_map_page_and_detail_carry_pins_attribution_and_demo_label PASSED
tests/test_map_weather.py::test_pin_data_is_escaped_in_html PASSED
tests/test_map_weather.py::test_tiles_can_be_disabled PASSED
tests/test_map_weather.py::test_diagram_has_one_line_per_live_route PASSED
tests/test_map_weather.py::test_diagram_empty_state PASSED
tests/test_map_weather.py::test_weather_success_and_cache PASSED
tests/test_map_weather.py::test_weather_failure_never_invents_data PASSED
tests/test_map_weather.py::test_weather_route_and_disabled_flag PASSED
tests/test_map_weather.py::test_csp_allows_only_osm_tiles_as_external_resource PASSED
tests/test_my_routes.py::test_my_routes_redirects_visitors_to_login_and_returns_after_signing_in PASSED
tests/test_my_routes.py::test_login_returns_to_the_page_that_asked_for_it PASSED
tests/test_my_routes.py::test_next_parameter_cannot_redirect_off_site PASSED
tests/test_my_routes.py::test_message_shown_when_redirected PASSED
tests/test_my_routes.py::test_my_routes_shows_only_followed_routes PASSED
tests/test_my_routes.py::test_route_with_no_notices_shows_empty_state PASSED
tests/test_my_routes.py::test_routes_in_url_are_ignored_now PASSED
tests/test_my_routes.py::test_follow_button_is_present_for_visitors_and_needs_login_to_act PASSED
tests/test_notifications.py::test_notification_created_once_per_subscription_and_revision PASSED
tests/test_notifications.py::test_demo_notifications_are_logged_not_claimed_delivered PASSED
tests/test_notifications.py::test_each_revision_alerts_once PASSED
tests/test_notifications.py::test_route_filter_and_pause PASSED
tests/test_notifications.py::test_email_failure_is_recorded_and_retried PASSED
tests/test_notifications.py::test_email_not_configured_is_skipped_honestly PASSED
tests/test_parser.py::test_successful_extraction PASSED
tests/test_parser.py::test_date_only_end_means_end_of_local_day PASSED
tests/test_parser.py::test_withdrawn_status_and_unsafe_link PASSED
tests/test_parser.py::test_missing_fields_are_reported_not_invented PASSED
tests/test_parser.py::test_malformed_html_does_not_crash PASSED
tests/test_parser.py::test_empty_or_unrelated_page_returns_warning PASSED
tests/test_parser.py::test_rss_parsing PASSED
tests/test_parser.py::test_rss_rejects_entity_bombs PASSED
tests/test_parser.py::test_helpers PASSED
tests/test_routes.py::test_empty_state_before_first_collection PASSED
tests/test_routes.py::test_refresh_populates_dashboard PASSED
tests/test_routes.py::test_post_without_csrf_is_rejected PASSED
tests/test_routes.py::test_route_filter_matches_notices_with_multiple_routes PASSED
tests/test_routes.py::test_search_filters_status_type_and_date PASSED
tests/test_routes.py::test_invalid_filter_values_are_ignored_with_message PASSED
tests/test_routes.py::test_notice_detail_shows_history_and_missing_end_date PASSED
tests/test_routes.py::test_expired_notice_is_not_active_on_page PASSED
tests/test_routes.py::test_stale_data_labelled_after_failed_refresh PASSED
tests/test_routes.py::test_timezone_display_is_ist PASSED
tests/test_routes.py::test_refresh_cooldown PASSED
tests/test_routes.py::test_unknown_pages_and_api_errors PASSED
tests/test_routes.py::test_admin_requires_login PASSED
tests/test_routes.py::test_admin_disabled_without_token PASSED
tests/test_routes.py::test_admin_scenario_flow_and_subscription_validation PASSED
tests/test_routes.py::test_security_headers_and_health PASSED
tests/test_routes.py::test_session_cookie_has_its_own_name PASSED
tests/test_scheduler.py::test_due_logic_respects_refresh_interval PASSED
tests/test_scheduler.py::test_scheduler_tick_runs_only_due_sources PASSED
tests/test_timeutil.py::test_storage_is_utc_and_display_is_ist PASSED
tests/test_timeutil.py::test_naive_datetimes_are_rejected PASSED
tests/test_timeutil.py::test_local_day_bounds_cross_utc_dates PASSED
tests/test_timeutil.py::test_round_trip_and_humanize PASSED
tests/test_ui.py::test_theme_and_layout_controls_present_but_developer_view_is_admin_only PASSED
tests/test_ui.py::test_route_colours_are_stable_and_bounded PASSED
tests/test_ui.py::test_developer_details_reach_admins_only PASSED
tests/test_ui.py::test_back_button_on_every_page_except_notices PASSED
tests/test_ui.py::test_recent_changes_panel_lists_revisions PASSED
tests/test_ui.py::test_follow_buttons_and_feed_rows_render PASSED
tests/test_ui.py::test_no_inline_scripts_or_styles PASSED
tests/test_ui.py::test_every_page_renders PASSED
tests/test_ui.py::test_old_demo_feed_is_upgraded_in_place_without_changing_times PASSED
tests/test_ui.py::test_corrupt_demo_feed_is_rebuilt PASSED
============================= 120 passed in 9.21s ==============================
```
