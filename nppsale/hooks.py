app_name = "nppsale"
app_title = "NPP Sale"
app_publisher = "Huy Chien"
app_description = "ERP van hanh nha phan phoi (chuyen tu npp.sale)"
app_email = "mrhuychien@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "nppsale",
# 		"logo": "/assets/nppsale/logo.png",
# 		"title": "NPP Sale",
# 		"route": "/nppsale",
# 		"has_permission": "nppsale.api.permission.has_app_permission",
# 	}
# ]

# The dock, the rail down the left of the desk, is a document rather than a hook. Author it in
# Manage Dock on a developer-mode site and press Export to App, and it is written to
# `nppsale/dock/nppsale/nppsale.json` for git to carry. An app that ships none has no
# rail: its sidebar gets a switcher in the header instead.
#
# A companion app, one that extends a host app rather than standing on its own, says so with
# `mount_on` on that same record, and its entries are appended to the host's rail. Mounting keeps
# the companion off the apps screen, so it takes precedence over any add_to_apps_screen above.

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/nppsale/css/nppsale.css"
# app_include_js = "/assets/nppsale/js/nppsale.js"

# include js, css files in header of web template
# web_include_css = "/assets/nppsale/css/nppsale.css"
# web_include_js = "/assets/nppsale/js/nppsale.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "nppsale/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_kanban_js = {"doctype" : "public/js/doctype_kanban.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "nppsale/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "nppsale.utils.jinja_methods",
# 	"filters": "nppsale.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "nppsale.install.before_install"
# after_install = "nppsale.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "nppsale.uninstall.before_uninstall"
# after_uninstall = "nppsale.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "nppsale.utils.before_app_install"
# after_app_install = "nppsale.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "nppsale.utils.before_app_uninstall"
# after_app_uninstall = "nppsale.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "nppsale.build.after_build"

# To hook into the build process of other apps
# The list of apps being built is passed as an argument

# after_app_build = "nppsale.build.after_app_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "nppsale.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["nppsale.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"nppsale.tasks.all"
# 	],
# 	"daily": [
# 		"nppsale.tasks.daily"
# 	],
# 	"hourly": [
# 		"nppsale.tasks.hourly"
# 	],
# 	"weekly": [
# 		"nppsale.tasks.weekly"
# 	],
# 	"monthly": [
# 		"nppsale.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "nppsale.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "nppsale.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "nppsale.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "nppsale.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["nppsale.utils.before_request"]
# after_request = ["nppsale.utils.after_request"]

# Job Events
# ----------
# before_job = ["nppsale.utils.before_job"]
# after_job = ["nppsale.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"nppsale.auth.validate"
# ]

# on_social_login = "nppsale.auth.on_social_login"

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

# ── Portal SPA (/nppsale/…) ─────────────────────────────────────────────────────
# Mọi đường dẫn dưới /nppsale/ trả về vỏ SPA (www/nppsale); router phía trình duyệt lo phần còn lại.
website_route_rules = [
	{"from_route": "/nppsale/<path:app_path>", "to_route": "nppsale"},
]
# sw.js + manifest phục vụ không cache, đúng scope /nppsale/ (xem nppsale/portal/tinh.py)
page_renderer = ["nppsale.portal.tinh.TepTinhPortal"]
