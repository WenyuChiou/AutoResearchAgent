/* Preserve the installed-browser entry point for the unified current-project UI.
 * The shared driver uses real saved deliveries and checks the same top project
 * selector, operation panel and languages, with automatic inline result binding.
 * Legacy --views-config options remain accepted by the argument parser; the
 * deterministic test owns its authored historical shell and saved deliveries.
 */
'use strict';
require('./project-unified-test.cjs');
