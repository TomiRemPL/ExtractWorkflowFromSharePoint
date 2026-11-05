CREATE OR REPLACE PACKAGE "SHP_API" AS
    /**
     * Executes an HTTPS GET request against SharePoint SE using NTLMv2.
     *
     * The invoking schema requires a network ACL grant for the SharePoint host.
     * The wallet must trust the SharePoint TLS certificate chain. Redirects are
     * disabled during authentication so credentials cannot be sent to another
     * origin. Responses larger than 10 MiB are rejected.
     *
     * @param p_url Complete HTTPS URL, limited to 4000 bytes
     * @param p_username Active Directory login without a domain prefix
     * @param p_password Active Directory password
     * @param p_domain Active Directory NetBIOS domain name
     * @param p_wallet_path Oracle wallet path in file:... or system: form
     * @param p_wallet_pwd Wallet password, or NULL for an auto-login wallet
     * @param p_accept Accept request header
     * @return SharePoint response body for HTTP 200 as a temporary CLOB
     * @raises -20001 for invalid arguments
     * @raises -20002 when the NTLM challenge is missing or malformed
     * @raises -20003 when an NTLM message cannot be decoded
     * @raises -20004 when the NTLM challenge uses unsupported capabilities
     * @raises -20005 when the response exceeds the configured limit
     * @raises -20006 when TLS channel binding is required
     * @raises -20007 when SharePoint returns a non-200 response
    FUNCTION make_get_request(
        p_url			IN VARCHAR2,
        p_username		IN VARCHAR2,
        p_password		IN VARCHAR2,
        p_domain		IN VARCHAR2,
        p_wallet_path	IN VARCHAR2,
        p_wallet_pwd	IN VARCHAR2 DEFAULT NULL,
        p_accept		IN VARCHAR2 DEFAULT 'application/json;odata=verbose'
    ) RETURN CLOB;
     */

    /**
     * Executes an HTTPS POST request against SharePoint SE using NTLMv2.
     *
     * The invoking schema requires a network ACL grant for the SharePoint host.
     * The wallet must trust the SharePoint TLS certificate chain. Redirects are
     * disabled during authentication so credentials cannot be sent to another
     * origin. Responses larger than 10 MiB are rejected.
     *
     * @param p_url Complete HTTPS URL, limited to 4000 bytes
     * @param p_username Active Directory login without a domain prefix
     * @param p_password Active Directory password
     * @param p_domain Active Directory NetBIOS domain name
     * @param p_wallet_path Oracle wallet path in file:... or system: form
     * @param p_wallet_pwd Wallet password, or NULL for an auto-login wallet
     * @param p_body Request body sent as UTF-8 bytes, or NULL for an empty request body
     * @param p_content_type Content-Type request header; charset is normalized to UTF-8
     * @param p_accept Accept request header
     * @return SharePoint response body for HTTP 200, 201, 202, or 204 as a temporary CLOB
     * @raises -20001 for invalid arguments
     * @raises -20002 when the NTLM challenge is missing or malformed
     * @raises -20003 when an NTLM message cannot be decoded
     * @raises -20004 when the NTLM challenge uses unsupported capabilities
     * @raises -20005 when the response exceeds the configured limit
     * @raises -20006 when TLS channel binding is required
     * @raises -20007 when SharePoint returns an unsuccessful response
    FUNCTION make_post_request(
        p_url			IN VARCHAR2,
        p_username		IN VARCHAR2,
        p_password		IN VARCHAR2,
        p_domain		IN VARCHAR2,
        p_wallet_path	IN VARCHAR2,
        p_wallet_pwd	IN VARCHAR2 DEFAULT NULL,
        p_body			IN CLOB DEFAULT NULL,
        p_content_type	IN VARCHAR2 DEFAULT 'application/json;odata=verbose',
        p_accept		IN VARCHAR2 DEFAULT 'application/json;odata=verbose'
    ) RETURN CLOB;
     */

    /**
     * Executes an HTTPS GET request using environment-specific SharePoint settings.
     *
     * Credentials and wallet settings are resolved from LCDT.PRV using the
     * environment returned by LCDT.PUB.get_env.
     *
     * @param p_url Complete HTTPS URL, limited to 4000 bytes
     * @return SharePoint response body for HTTP 200 as a temporary CLOB
     */
    FUNCTION shp_get(
        p_url	IN VARCHAR2
    ) RETURN CLOB;

    /**
     * Executes an HTTPS POST request using environment-specific SharePoint settings.
     *
     * Credentials and wallet settings are resolved from LCDT.PRV using the
     * environment returned by LCDT.PUB.get_env.
     *
     * @param p_url Complete HTTPS URL, limited to 4000 bytes
     * @param p_body Request body to send, or NULL for an empty request body
     * @return SharePoint response body for HTTP 200, 201, 202, or 204 as a temporary CLOB
     */
    FUNCTION shp_post(
        p_url	IN VARCHAR2,
        p_body	IN CLOB DEFAULT NULL
    ) RETURN CLOB;

  /**
   * Resolves a user and registers them in the site collection if needed.
   * Registration does not grant permissions or create an Active Directory account.
   *
   * @param p_site_url SharePoint site URL, without /_api
   * @param p_login_name Claims login, such as i:0#.w|DOMAIN\login; email lookup is not supported
   * @return Positive numeric user ID scoped to the target site collection
   * @raises -20001 for invalid input or a login resolving to a group
   * @raises -20008 for a malformed user response
   * Authentication, HTTP, and user resolution failures propagate as exceptions.
   */
  FUNCTION ensure_user_id(
    p_site_url	IN VARCHAR2,
    p_login_name	IN VARCHAR2
  ) RETURN NUMBER;

    /**
     * Gets one SharePoint list item and returns a workflow-friendly JSON envelope.
     *
     * @param p_site_url SharePoint site URL, without /_api
     * @param p_list_title SharePoint list title
     * @param p_item_id SharePoint list item ID
     * @param p_query Optional OData query string, with or without leading ?
     * @param p_raise_on_error Y (default) propagates original exceptions; N or NULL returns error JSON
     *                         Case and surrounding spaces are ignored; other values return -20001 error JSON
     * @return JSON CLOB with success, operation, message, item_id, and data
     */
    FUNCTION get_list_item(
		p_site_url	IN VARCHAR2,
		p_list_title	IN VARCHAR2,
		p_item_id	IN NUMBER,
		p_query		IN VARCHAR2 DEFAULT NULL,
		p_raise_on_error	IN VARCHAR2 DEFAULT 'Y'
    ) RETURN CLOB;

    /**
     * Gets SharePoint list items and returns a workflow-friendly JSON envelope.
     *
     * @param p_site_url SharePoint site URL, without /_api
     * @param p_list_title SharePoint list title
     * @param p_query Optional OData query string, with or without leading ?
     * @param p_raise_on_error Y (default) propagates original exceptions; N or NULL returns error JSON
     *                         Case and surrounding spaces are ignored; other values return -20001 error JSON
     * @return JSON CLOB with success, operation, message, and data array
     */
    FUNCTION get_list_items(
		p_site_url	IN VARCHAR2,
		p_list_title	IN VARCHAR2,
		p_query		IN VARCHAR2 DEFAULT NULL,
		p_raise_on_error	IN VARCHAR2 DEFAULT 'Y'
    ) RETURN CLOB;

    /**
     * Adds one SharePoint list item and returns a workflow-friendly JSON envelope.
     *
     * @param p_site_url SharePoint site URL, without /_api
     * @param p_list_title SharePoint list title
     * @param p_fields_json JSON object with SharePoint field internal names and values
     * @param p_raise_on_error Y (default) propagates original exceptions; N or NULL returns error JSON
     *                         Case and surrounding spaces are ignored; other values return -20001 error JSON
     * @return JSON CLOB with success, operation, message, item_id, and data
     */
    FUNCTION add_list_item(
		p_site_url	IN VARCHAR2,
		p_list_title	IN VARCHAR2,
		p_fields_json	IN CLOB,
		p_raise_on_error	IN VARCHAR2 DEFAULT 'Y'
    ) RETURN CLOB;

    /**
     * Updates SharePoint list item fields and returns a workflow-friendly JSON envelope.
     *
     * @param p_site_url SharePoint site URL, without /_api
     * @param p_list_title SharePoint list title
     * @param p_item_id SharePoint list item ID
     * @param p_fields_json JSON object with SharePoint field internal names and values
     * @param p_etag SharePoint ETag to match, or * to overwrite current item
     * @param p_raise_on_error Y (default) propagates original exceptions; N or NULL returns error JSON
     *                         Case and surrounding spaces are ignored; other values return -20001 error JSON
     * @return JSON CLOB with success, operation, message, and item_id
     */
    FUNCTION update_list_item(
		p_site_url	IN VARCHAR2,
		p_list_title	IN VARCHAR2,
		p_item_id	IN NUMBER,
		p_fields_json	IN CLOB,
		p_etag		IN VARCHAR2 DEFAULT '*',
		p_raise_on_error	IN VARCHAR2 DEFAULT 'Y'
    ) RETURN CLOB;

    /**
     * Copies all attachments from one SharePoint list item to another.
     * Existing attachments on the source item are not removed. A destination
     * attachment with the same name (case-insensitive) has its content overwritten
     * using PUT, without deleting it first. Other destination attachments are
     * unchanged. Attachments larger than 100 MiB are rejected.
     * Copies are not atomic; completed writes remain if a later attachment fails.
     *
     * @param p_source_site_url Source SharePoint site URL, without /_api
     * @param p_source_list_title Source list title
     * @param p_source_item_id Source list item ID
     * @param p_target_site_url Target SharePoint site URL, without /_api
     * @param p_target_list_title Target list title
     * @param p_target_item_id Target list item ID
     * @param p_raise_on_error Y (default) propagates exceptions; N or NULL returns error JSON
     * @return Workflow JSON with copied attachment names and count
     */
    FUNCTION copy_list_item_attachments(
		p_source_site_url	IN VARCHAR2,
		p_source_list_title	IN VARCHAR2,
		p_source_item_id	IN NUMBER,
		p_target_site_url	IN VARCHAR2,
		p_target_list_title	IN VARCHAR2,
		p_target_item_id	IN NUMBER,
		p_raise_on_error	IN VARCHAR2 DEFAULT 'Y'
    ) RETURN CLOB;

  /**
    * Replaces regular direct roles for selected users, Active Directory security groups,
    * and SharePoint groups on one item.
    * REPLACE preserves system-managed (RoleTypeKind = 1) and hidden role bindings;
    * success requires the requested role to be the only regular direct role.
   * Adds and verifies each requested role before removing obsolete role bindings;
   * a failure during cleanup can temporarily leave both old and new roles assigned.
   * Inherited permissions are copied before creating a unique permission scope.
   * REMOVE_DIRECT removes only a direct assignment and is a no-op for inherited ACLs.
  * REMOVE_DIRECT rejects assignments containing system-managed or hidden bindings.
   * It cannot revoke access through other principals or inherited permissions.
   * Other principals and children's unique scopes are not explicitly modified.
   * Calls are not atomic; serialize permission updates for each item.
	* The executing account's own direct assignment cannot be changed.
  * For non-site-collection administrators, a SharePoint group with that account as a direct member
	* permits only unchanged REPLACE or REPLACE with a role granting ManagePermissions.
	* Calls containing only unchanged such groups do not break inheritance.
  * REMOVE_DIRECT remains blocked for groups with the executing account as a direct member.
  * Groups with directory principals are accepted, but AD membership is not expanded or checked;
  * changing or removing such an assignment may change the executing account's effective access.
   *
   * @param p_site_url SharePoint site URL, without /_api
   * @param p_list_title List or document library title
   * @param p_item_id Positive list item ID, including a document's list item ID
    * @param p_permissions_json Nonempty JSON array. Each entry has a principal selector:
    *   USER or DIRECTORY_GROUP: type and login_name; SHAREPOINT_GROUP: type and exactly one
    *   of group_name/group_id. DIRECTORY_GROUP login_name must resolve to an AD security group.
   *   Omitted action or REPLACE requires exactly one role_name/role_id and replaces
  *   that principal's regular direct roles. REMOVE_DIRECT accepts no role selector and removes
   *   all direct bindings. All entries in one call must use the same action.
   *   Names use the target web's language.
    *
    * REPLACE examples:
    *   [
    *     {"type":"USER","login_name":"i:0#.w|DOMAIN\\user","role_name":"Read"},
    *     {"type":"SHAREPOINT_GROUP","group_id":3033,"role_name":"Edit"}
    *   ]
    *   [
    *     {"type":"SHAREPOINT_GROUP","group_name":"rl9","role_name":"Edit"}
    *   ]
    *   [
    *     {"type":"DIRECTORY_GROUP","login_name":"GRUPA\\LUKAS_TRUCK","role_name":"Read"}
    *   ]
    *
    * REMOVE_DIRECT examples:
    *   [
    *     {"action":"REMOVE_DIRECT","type":"USER","login_name":"i:0#.w|DOMAIN\\user"},
    *     {"action":"REMOVE_DIRECT","type":"SHAREPOINT_GROUP","group_id":3033}
    *   ]
    *   [
    *     {"action":"REMOVE_DIRECT","type":"SHAREPOINT_GROUP","group_name":"rl9"}
    *   ]
    *   [
    *     {"action":"REMOVE_DIRECT","type":"DIRECTORY_GROUP","login_name":"GRUPA\\LUKAS_TRUCK"}
    *   ]
   * @param p_raise_on_error Y (default) propagates exceptions; N or NULL returns error JSON
   * @return Workflow JSON with progress, changed roles, and partial-write diagnostics
   */
  FUNCTION set_list_item_permissions(
	p_site_url	IN VARCHAR2,
	p_list_title	IN VARCHAR2,
	p_item_id	IN NUMBER,
	p_permissions_json IN CLOB,
	p_raise_on_error IN VARCHAR2 DEFAULT 'Y'
  ) RETURN CLOB;

END "SHP_API";
/
