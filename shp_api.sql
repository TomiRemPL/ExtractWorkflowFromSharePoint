create or replace PACKAGE "SHP_API" AS
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
     * @param p_body Request body to send, or NULL for an empty request body
     * @param p_content_type Content-Type request header
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
     * Gets one SharePoint list item and returns a workflow-friendly JSON envelope.
     *
     * @param p_site_url SharePoint site URL, without /_api
     * @param p_list_title SharePoint list title
     * @param p_item_id SharePoint list item ID
     * @param p_query Optional OData query string, with or without leading ?
     * @return JSON CLOB with success, operation, message, item_id, and data
     */
    FUNCTION get_list_item(
        p_site_url	IN VARCHAR2,
        p_list_title	IN VARCHAR2,
        p_item_id	IN NUMBER,
        p_query		IN VARCHAR2 DEFAULT NULL
    ) RETURN CLOB;

    /**
     * Gets SharePoint list items and returns a workflow-friendly JSON envelope.
     *
     * @param p_site_url SharePoint site URL, without /_api
     * @param p_list_title SharePoint list title
     * @param p_query Optional OData query string, with or without leading ?
     * @return JSON CLOB with success, operation, message, and data array
     */
    FUNCTION get_list_items(
        p_site_url	IN VARCHAR2,
        p_list_title	IN VARCHAR2,
        p_query		IN VARCHAR2 DEFAULT NULL
    ) RETURN CLOB;

    /**
     * Adds one SharePoint list item and returns a workflow-friendly JSON envelope.
     *
     * @param p_site_url SharePoint site URL, without /_api
     * @param p_list_title SharePoint list title
     * @param p_fields_json JSON object with SharePoint field internal names and values
     * @return JSON CLOB with success, operation, message, item_id, and data
     */
    FUNCTION add_list_item(
        p_site_url	IN VARCHAR2,
        p_list_title	IN VARCHAR2,
        p_fields_json	IN CLOB
    ) RETURN CLOB;

    /**
     * Updates SharePoint list item fields and returns a workflow-friendly JSON envelope.
     *
     * @param p_site_url SharePoint site URL, without /_api
     * @param p_list_title SharePoint list title
     * @param p_item_id SharePoint list item ID
     * @param p_fields_json JSON object with SharePoint field internal names and values
     * @param p_etag SharePoint ETag to match, or * to overwrite current item
     * @return JSON CLOB with success, operation, message, and item_id
     */
    FUNCTION update_list_item(
        p_site_url	IN VARCHAR2,
        p_list_title	IN VARCHAR2,
        p_item_id	IN NUMBER,
        p_fields_json	IN CLOB,
        p_etag		IN VARCHAR2 DEFAULT '*'
    ) RETURN CLOB;

END "SHP_API";
/
create or replace PACKAGE BODY "SHP_API" AS

    C_TRANSFER_TIMEOUT	CONSTANT PLS_INTEGER := 60;
    C_READ_CHUNK_SIZE	CONSTANT PLS_INTEGER := 32767;
    C_MAX_RESPONSE_SIZE	CONSTANT PLS_INTEGER := 10 * 1024 * 1024;

    C_NEGOTIATE_UNICODE			CONSTANT NUMBER := 1;
    C_REQUEST_TARGET			CONSTANT NUMBER := 4;
    C_NEGOTIATE_NTLM			CONSTANT NUMBER := 512;
    C_NEGOTIATE_ALWAYS_SIGN		CONSTANT NUMBER := 32768;
    C_NEGOTIATE_EXTENDED_SESSION	CONSTANT NUMBER := 524288;
    C_NEGOTIATE_TARGET_INFO		CONSTANT NUMBER := 8388608;
    C_NEGOTIATE_128				CONSTANT NUMBER := 536870912;
    C_NEGOTIATE_56				CONSTANT NUMBER := 2147483648;

    C_CLIENT_FLAGS CONSTANT NUMBER :=
        C_NEGOTIATE_UNICODE +
        C_REQUEST_TARGET +
        C_NEGOTIATE_NTLM +
        C_NEGOTIATE_ALWAYS_SIGN +
        C_NEGOTIATE_EXTENDED_SESSION +
        C_NEGOTIATE_TARGET_INFO +
        C_NEGOTIATE_128 +
        C_NEGOTIATE_56;

    TYPE t_ntlm_type2 IS RECORD (
        message			RAW(32767),
        flags			NUMBER,
        server_challenge	RAW(8),
        target_info		RAW(32767),
        timestamp		RAW(8),
        mic_required		BOOLEAN
    );

	TYPE t_shp_settings IS RECORD (
		wallet_path	VARCHAR2(256),
		wallet_pwd	VARCHAR2(256),
		username	VARCHAR2(256),
		password	VARCHAR2(256)
	);

    FUNCTION raw_append(
        p_left	IN RAW,
        p_right	IN RAW
    ) RETURN RAW IS
    BEGIN
        RETURN UTL_RAW.concat(p_left, p_right);
    END raw_append;

    FUNCTION zero_raw(p_length IN PLS_INTEGER) RETURN RAW IS
    BEGIN
        IF p_length IS NULL OR p_length < 1 THEN
            RETURN NULL;
        END IF;

        RETURN HEXTORAW(RPAD('00', p_length * 2, '0'));
    END zero_raw;

    FUNCTION encode_le(
        p_value	IN NUMBER,
        p_bytes	IN PLS_INTEGER
    ) RETURN RAW IS
        l_value	NUMBER := p_value;
        l_byte		PLS_INTEGER;
        l_hex		VARCHAR2(32767);
    BEGIN
        IF p_value < 0 OR p_bytes < 1 THEN
            raise_application_error(-20003, 'Invalid little-endian value.');
        END IF;

        FOR i IN 1 .. p_bytes LOOP
            l_byte := TRUNC(MOD(l_value, 256));
            l_hex := l_hex ||
                SUBSTR('0123456789ABCDEF', TRUNC(l_byte / 16) + 1, 1) ||
                SUBSTR('0123456789ABCDEF', MOD(l_byte, 16) + 1, 1);
            l_value := TRUNC(l_value / 256);
        END LOOP;

        IF l_value > 0 THEN
            raise_application_error(-20003, 'Little-endian value exceeds its field.');
        END IF;

        RETURN HEXTORAW(l_hex);
    END encode_le;

    FUNCTION decode_le(
        p_value	IN RAW,
        p_position	IN PLS_INTEGER,
        p_bytes	IN PLS_INTEGER
    ) RETURN NUMBER IS
        l_result	NUMBER := 0;
        l_byte		NUMBER;
    BEGIN
        IF p_position < 1 OR p_bytes < 1 OR
            p_position + p_bytes - 1 > NVL(UTL_RAW.length(p_value), 0)
        THEN
            raise_application_error(-20003, 'NTLM field is outside the message.');
        END IF;

        FOR i IN 0 .. p_bytes - 1 LOOP
            l_byte := TO_NUMBER(RAWTOHEX(UTL_RAW.substr(p_value, p_position + i, 1)), 'XX');
            l_result := l_result + l_byte * POWER(256, i);
        END LOOP;

        RETURN l_result;
    END decode_le;

    FUNCTION to_utf16le(p_value IN VARCHAR2) RETURN RAW IS
    BEGIN
        RETURN UTL_I18N.string_to_raw(p_value, 'AL16UTF16LE');
    END to_utf16le;

    FUNCTION encode_base64(p_value IN RAW) RETURN VARCHAR2 IS
    BEGIN
        RETURN REPLACE(
            REPLACE(UTL_RAW.cast_to_varchar2(UTL_ENCODE.base64_encode(p_value)), CHR(13)),
            CHR(10)
        );
    END encode_base64;

    FUNCTION decode_base64(p_value IN VARCHAR2) RETURN RAW IS
        l_value VARCHAR2(32767);
    BEGIN
        l_value := REGEXP_REPLACE(p_value, '[[:space:]]', '');

        IF l_value IS NULL OR MOD(LENGTH(l_value), 4) <> 0 OR
            NOT REGEXP_LIKE(l_value, '^[A-Za-z0-9+/]+={0,2}$')
        THEN
            raise_application_error(-20003, 'The NTLM challenge is not valid Base64.');
        END IF;

        RETURN UTL_ENCODE.base64_decode(UTL_RAW.cast_to_raw(l_value));
    EXCEPTION
        WHEN OTHERS THEN
            IF SQLCODE BETWEEN -20099 AND -20000 THEN
                RAISE;
            END IF;
            raise_application_error(-20003, 'The NTLM challenge cannot be decoded.');
    END decode_base64;

    FUNCTION has_flag(
        p_flags	IN NUMBER,
        p_flag		IN NUMBER
    ) RETURN BOOLEAN IS
    BEGIN
        RETURN BITAND(p_flags, p_flag) = p_flag;
    END has_flag;

    FUNCTION security_buffer(
        p_length	IN PLS_INTEGER,
        p_offset	IN PLS_INTEGER
    ) RETURN RAW IS
    BEGIN
        IF p_length < 0 OR p_length > 32767 OR p_offset < 0 THEN
            raise_application_error(-20003, 'Invalid NTLM security buffer.');
        END IF;

        RETURN raw_append(
            raw_append(encode_le(p_length, 2), encode_le(p_length, 2)),
            encode_le(p_offset, 4)
        );
    END security_buffer;

    PROCEDURE read_security_buffer(
        p_message	IN RAW,
        p_position	IN PLS_INTEGER,
        p_data		OUT RAW
    ) IS
        l_length	PLS_INTEGER;
        l_max_length	PLS_INTEGER;
        l_offset	PLS_INTEGER;
        l_total		PLS_INTEGER := NVL(UTL_RAW.length(p_message), 0);
    BEGIN
        l_length := decode_le(p_message, p_position, 2);
        l_max_length := decode_le(p_message, p_position + 2, 2);
        l_offset := decode_le(p_message, p_position + 4, 4);

        IF l_length > 32767 OR l_max_length < l_length OR
            l_offset < 0 OR l_offset + l_length > l_total
        THEN
            raise_application_error(-20003, 'NTLM security buffer is outside the message.');
        END IF;

        IF l_length = 0 THEN
            p_data := NULL;
        ELSE
            p_data := UTL_RAW.substr(p_message, l_offset + 1, l_length);
        END IF;
    END read_security_buffer;

    FUNCTION ntlm_mac(
        p_key	IN RAW,
        p_data	IN RAW
    ) RETURN RAW IS
    BEGIN
        RETURN DBMS_CRYPTO.mac(
            src => p_data,
            typ => DBMS_CRYPTO.hmac_md5,
            key => p_key
        );
    END ntlm_mac;

    FUNCTION current_windows_timestamp RETURN RAW IS
        l_utc_timestamp	TIMESTAMP := SYS_EXTRACT_UTC(SYSTIMESTAMP);
        l_seconds		NUMBER;
    BEGIN
        l_seconds :=
            (TRUNC(CAST(l_utc_timestamp AS DATE)) - DATE '1970-01-01') * 86400 +
            EXTRACT(HOUR FROM l_utc_timestamp) * 3600 +
            EXTRACT(MINUTE FROM l_utc_timestamp) * 60 +
            EXTRACT(SECOND FROM l_utc_timestamp);

        RETURN encode_le(TRUNC((l_seconds + 11644473600) * 10000000), 8);
    END current_windows_timestamp;

    FUNCTION build_type1 RETURN RAW IS
        l_message RAW(32767);
    BEGIN
        l_message := HEXTORAW('4E544C4D53535000');
        l_message := raw_append(l_message, encode_le(1, 4));
        l_message := raw_append(l_message, encode_le(C_CLIENT_FLAGS, 4));
        l_message := raw_append(l_message, security_buffer(0, 32));
        l_message := raw_append(l_message, security_buffer(0, 32));

        RETURN l_message;
    END build_type1;

    PROCEDURE parse_type2(
        p_token	IN VARCHAR2,
        p_type2	OUT t_ntlm_type2
    ) IS
        l_position	PLS_INTEGER := 1;
        l_av_id		PLS_INTEGER;
        l_av_length	PLS_INTEGER;
        l_av_value	RAW(32767);
        l_found_eol	BOOLEAN := FALSE;
    BEGIN
        p_type2.message := decode_base64(p_token);

        IF NVL(UTL_RAW.length(p_type2.message), 0) < 48 OR
            RAWTOHEX(UTL_RAW.substr(p_type2.message, 1, 8)) <> '4E544C4D53535000' OR
            decode_le(p_type2.message, 9, 4) <> 2 OR
            decode_le(p_type2.message, 45, 4) < 48
        THEN
            raise_application_error(-20002, 'The server returned an invalid NTLM Type 2 message.');
        END IF;

        p_type2.flags := decode_le(p_type2.message, 21, 4);
        p_type2.server_challenge := UTL_RAW.substr(p_type2.message, 25, 8);
        read_security_buffer(p_type2.message, 41, p_type2.target_info);
        p_type2.timestamp := NULL;
        p_type2.mic_required := FALSE;

        IF p_type2.server_challenge = zero_raw(8) OR
            NOT has_flag(p_type2.flags, C_NEGOTIATE_UNICODE) OR
            NOT has_flag(p_type2.flags, C_NEGOTIATE_NTLM) OR
            NOT has_flag(p_type2.flags, C_NEGOTIATE_EXTENDED_SESSION) OR
            NOT has_flag(p_type2.flags, C_NEGOTIATE_TARGET_INFO) OR
            p_type2.target_info IS NULL
        THEN
            raise_application_error(-20004, 'The server challenge does not support the required NTLMv2 capabilities.');
        END IF;

        WHILE l_position <= UTL_RAW.length(p_type2.target_info) LOOP
            IF l_position + 3 > UTL_RAW.length(p_type2.target_info) THEN
                raise_application_error(-20002, 'The NTLM target information is truncated.');
            END IF;

            l_av_id := decode_le(p_type2.target_info, l_position, 2);
            l_av_length := decode_le(p_type2.target_info, l_position + 2, 2);
            l_position := l_position + 4;

            IF l_position + l_av_length - 1 > UTL_RAW.length(p_type2.target_info) THEN
                raise_application_error(-20002, 'An NTLM target information value is truncated.');
            END IF;

            IF l_av_length = 0 THEN
                l_av_value := NULL;
            ELSE
                l_av_value := UTL_RAW.substr(p_type2.target_info, l_position, l_av_length);
            END IF;

            IF l_av_id = 0 THEN
                IF l_av_length <> 0 OR l_position - 1 <> UTL_RAW.length(p_type2.target_info) THEN
                    raise_application_error(-20002, 'The NTLM target information terminator is invalid.');
                END IF;
                l_found_eol := TRUE;
                EXIT;
            ELSIF l_av_id = 6 THEN
                IF l_av_length <> 4 THEN
                    raise_application_error(-20002, 'The NTLM flags attribute is invalid.');
                END IF;
                p_type2.mic_required := BITAND(decode_le(l_av_value, 1, 4), 2) = 2;
            ELSIF l_av_id = 7 THEN
                IF l_av_length <> 8 THEN
                    raise_application_error(-20002, 'The NTLM timestamp attribute is invalid.');
                END IF;
                p_type2.timestamp := l_av_value;
            ELSIF l_av_id = 10 THEN
                raise_application_error(
                    -20006,
                    'The server requires TLS channel binding, which UTL_HTTP cannot expose to NTLM.'
                );
            END IF;

            l_position := l_position + l_av_length;
        END LOOP;

        IF NOT l_found_eol THEN
            raise_application_error(-20002, 'The NTLM target information has no terminator.');
        END IF;
    END parse_type2;

    PROCEDURE build_type3(
        p_type1		IN RAW,
        p_type2		IN t_ntlm_type2,
        p_username		IN VARCHAR2,
        p_password		IN VARCHAR2,
        p_domain		IN VARCHAR2,
        p_message		OUT RAW
    ) IS
        l_client_challenge	RAW(8);
        l_timestamp		RAW(8);
        l_nt_hash			RAW(16);
        l_ntlmv2_hash		RAW(16);
        l_blob				RAW(32767);
        l_nt_proof			RAW(16);
        l_nt_response		RAW(32767);
        l_lm_response		RAW(24);
        l_session_base_key	RAW(16);
        l_domain_raw		RAW(32767);
        l_username_raw		RAW(32767);
        l_workstation_raw	RAW(32767);
        l_payload			RAW(32767);
        l_header			RAW(32767);
        l_zero_mic			RAW(16);
        l_mic				RAW(16);
        l_message_with_mic	RAW(32767);
        l_flags			NUMBER;
        l_payload_offset	PLS_INTEGER;
        l_domain_offset	PLS_INTEGER;
        l_username_offset	PLS_INTEGER;
        l_workstation_offset PLS_INTEGER;
        l_lm_offset		PLS_INTEGER;
        l_nt_offset		PLS_INTEGER;
        l_end_offset		PLS_INTEGER;
    BEGIN
        l_client_challenge := DBMS_CRYPTO.randombytes(8);
        l_timestamp := NVL(p_type2.timestamp, current_windows_timestamp());

        l_nt_hash := DBMS_CRYPTO.hash(
            src => to_utf16le(p_password),
            typ => DBMS_CRYPTO.hash_md4
        );
        l_ntlmv2_hash := ntlm_mac(
            l_nt_hash,
            to_utf16le(NLS_UPPER(p_username, 'NLS_SORT=BINARY') || p_domain)
        );

        l_blob := HEXTORAW('0101000000000000');
        l_blob := raw_append(l_blob, l_timestamp);
        l_blob := raw_append(l_blob, l_client_challenge);
        l_blob := raw_append(l_blob, zero_raw(4));
        l_blob := raw_append(l_blob, p_type2.target_info);
        l_blob := raw_append(l_blob, zero_raw(4));

        l_nt_proof := ntlm_mac(
            l_ntlmv2_hash,
            raw_append(p_type2.server_challenge, l_blob)
        );
        l_nt_response := raw_append(l_nt_proof, l_blob);

        IF p_type2.timestamp IS NOT NULL THEN
            l_lm_response := zero_raw(24);
        ELSE
            l_lm_response := raw_append(
                ntlm_mac(
                    l_ntlmv2_hash,
                    raw_append(p_type2.server_challenge, l_client_challenge)
                ),
                l_client_challenge
            );
        END IF;

        l_domain_raw := to_utf16le(p_domain);
        l_username_raw := to_utf16le(p_username);
        l_workstation_raw := NULL;
        l_flags := BITAND(p_type2.flags, C_CLIENT_FLAGS);
        l_payload_offset := CASE WHEN p_type2.mic_required THEN 80 ELSE 64 END;
        l_domain_offset := l_payload_offset;
        l_username_offset := l_domain_offset + NVL(UTL_RAW.length(l_domain_raw), 0);
        l_workstation_offset := l_username_offset + NVL(UTL_RAW.length(l_username_raw), 0);
        l_lm_offset := l_workstation_offset + NVL(UTL_RAW.length(l_workstation_raw), 0);
        l_nt_offset := l_lm_offset + UTL_RAW.length(l_lm_response);
        l_end_offset := l_nt_offset + UTL_RAW.length(l_nt_response);

        l_header := HEXTORAW('4E544C4D53535000');
        l_header := raw_append(l_header, encode_le(3, 4));
        l_header := raw_append(l_header, security_buffer(UTL_RAW.length(l_lm_response), l_lm_offset));
        l_header := raw_append(l_header, security_buffer(UTL_RAW.length(l_nt_response), l_nt_offset));
        l_header := raw_append(l_header, security_buffer(NVL(UTL_RAW.length(l_domain_raw), 0), l_domain_offset));
        l_header := raw_append(l_header, security_buffer(NVL(UTL_RAW.length(l_username_raw), 0), l_username_offset));
        l_header := raw_append(l_header, security_buffer(NVL(UTL_RAW.length(l_workstation_raw), 0), l_workstation_offset));
        l_header := raw_append(l_header, security_buffer(0, l_end_offset));
        l_header := raw_append(l_header, encode_le(l_flags, 4));

        IF p_type2.mic_required THEN
            l_zero_mic := zero_raw(16);
            l_header := raw_append(l_header, l_zero_mic);
        END IF;

        l_payload := raw_append(l_domain_raw, l_username_raw);
        l_payload := raw_append(l_payload, l_workstation_raw);
        l_payload := raw_append(l_payload, l_lm_response);
        l_payload := raw_append(l_payload, l_nt_response);
        p_message := raw_append(l_header, l_payload);

        IF p_type2.mic_required THEN
            l_session_base_key := ntlm_mac(l_ntlmv2_hash, l_nt_proof);
            l_mic := ntlm_mac(
                l_session_base_key,
                raw_append(raw_append(p_type1, p_type2.message), p_message)
            );
            l_message_with_mic := raw_append(
                raw_append(UTL_RAW.substr(p_message, 1, 64), l_mic),
                UTL_RAW.substr(p_message, 81, UTL_RAW.length(p_message) - 80)
            );
            p_message := l_message_with_mic;
        END IF;
    END build_type3;

    PROCEDURE drain_response(p_response IN OUT NOCOPY UTL_HTTP.resp) IS
        l_data RAW(32767);
    BEGIN
        BEGIN
            LOOP
                UTL_HTTP.read_raw(p_response, l_data, C_READ_CHUNK_SIZE);
            END LOOP;
        EXCEPTION
            WHEN UTL_HTTP.end_of_body THEN
                NULL;
        END;
    END drain_response;

    PROCEDURE read_response(
        p_response	IN OUT NOCOPY UTL_HTTP.resp,
        p_result	OUT CLOB
    ) IS
        l_text		VARCHAR2(32767);
        l_total_bytes	PLS_INTEGER := 0;
    BEGIN
        DBMS_LOB.createtemporary(p_result, FALSE, DBMS_LOB.SESSION);

        BEGIN
            LOOP
                UTL_HTTP.read_text(p_response, l_text, C_READ_CHUNK_SIZE);
                l_total_bytes := l_total_bytes + LENGTHB(l_text);

                IF l_total_bytes > C_MAX_RESPONSE_SIZE THEN
                    raise_application_error(-20005, 'The SharePoint response exceeds 10 MiB.');
                END IF;

                DBMS_LOB.writeappend(p_result, LENGTH(l_text), l_text);
            END LOOP;
        EXCEPTION
            WHEN UTL_HTTP.end_of_body THEN
                NULL;
        END;
    END read_response;

	PROCEDURE write_request_body(
		p_request	IN OUT NOCOPY UTL_HTTP.req,
		p_body		IN CLOB
	) IS
		l_offset	PLS_INTEGER := 1;
		l_length	PLS_INTEGER;
		l_chunk		VARCHAR2(32767);
	BEGIN
		IF p_body IS NULL THEN
			RETURN;
		END IF;

		l_length := DBMS_LOB.getlength(p_body);

		WHILE l_offset <= l_length LOOP
			l_chunk := DBMS_LOB.substr(p_body, C_READ_CHUNK_SIZE, l_offset);
			UTL_HTTP.write_text(p_request, l_chunk);
			l_offset := l_offset + LENGTH(l_chunk);
		END LOOP;
	END write_request_body;

	FUNCTION clob_lengthb(p_body IN CLOB) RETURN PLS_INTEGER IS
		l_offset	PLS_INTEGER := 1;
		l_length	PLS_INTEGER;
		l_total		PLS_INTEGER := 0;
		l_chunk		VARCHAR2(32767);
	BEGIN
		IF p_body IS NULL THEN
			RETURN 0;
		END IF;

		l_length := DBMS_LOB.getlength(p_body);

		WHILE l_offset <= l_length LOOP
			l_chunk := DBMS_LOB.substr(p_body, C_READ_CHUNK_SIZE, l_offset);
			l_total := l_total + LENGTHB(l_chunk);
			l_offset := l_offset + LENGTH(l_chunk);
		END LOOP;

		RETURN l_total;
	END clob_lengthb;

	FUNCTION is_success_response(
		p_method		IN VARCHAR2,
		p_status_code	IN PLS_INTEGER
	) RETURN BOOLEAN IS
	BEGIN
		IF p_method = 'GET' THEN
			RETURN p_status_code = UTL_HTTP.HTTP_OK;
		END IF;

		RETURN p_status_code IN (200, 201, 202, 204);
	END is_success_response;

    FUNCTION make_ntlm_request(
        p_url			IN VARCHAR2,
        p_method		IN VARCHAR2,
        p_username		IN VARCHAR2,
        p_password		IN VARCHAR2,
        p_domain		IN VARCHAR2,
        p_wallet_path	IN VARCHAR2,
        p_wallet_pwd	IN VARCHAR2 DEFAULT NULL,
		p_body			IN CLOB DEFAULT NULL,
		p_content_type	IN VARCHAR2 DEFAULT NULL,
		p_accept		IN VARCHAR2 DEFAULT 'application/json;odata=verbose',
		p_x_request_digest	IN VARCHAR2 DEFAULT NULL,
		p_if_match		IN VARCHAR2 DEFAULT NULL,
		p_x_http_method		IN VARCHAR2 DEFAULT NULL
    ) RETURN CLOB IS
        l_request			UTL_HTTP.req;
        l_response			UTL_HTTP.resp;
        l_request_context	UTL_HTTP.request_context_key;
        l_type1			RAW(32767);
        l_type2			t_ntlm_type2;
        l_type2_token		VARCHAR2(32767);
        l_type3			RAW(32767);
        l_header_name		VARCHAR2(256);
        l_header_value		VARCHAR2(32767);
        l_result			CLOB;
        l_status_code		PLS_INTEGER;
        l_reason_phrase		VARCHAR2(256);
        l_response_open		BOOLEAN := FALSE;
        l_context_created	BOOLEAN := FALSE;
        l_settings_saved	BOOLEAN := FALSE;
        l_old_persistent	BOOLEAN;
        l_old_max_conns		PLS_INTEGER;
        l_old_timeout		PLS_INTEGER;
        l_old_error_check	BOOLEAN;
        l_old_connections	UTL_HTTP.connection_table;
        l_current_connections UTL_HTTP.connection_table;
        l_error_code		NUMBER;
        l_http_error		VARCHAR2(4000);

        FUNCTION same_boolean(
            p_left	IN BOOLEAN,
            p_right	IN BOOLEAN
        ) RETURN BOOLEAN IS
        BEGIN
            RETURN (p_left AND p_right) OR
                (NOT p_left AND NOT p_right) OR
                (p_left IS NULL AND p_right IS NULL);
        END same_boolean;

        FUNCTION connection_existed(p_connection IN UTL_HTTP.connection) RETURN BOOLEAN IS
        BEGIN
            IF l_old_connections.COUNT > 0 THEN
                FOR i IN 1 .. l_old_connections.COUNT LOOP
                    IF NVL(l_old_connections(i).host, CHR(0)) = NVL(p_connection.host, CHR(0)) AND
                        NVL(l_old_connections(i).port, -1) = NVL(p_connection.port, -1) AND
                        NVL(l_old_connections(i).proxy_host, CHR(0)) = NVL(p_connection.proxy_host, CHR(0)) AND
                        NVL(l_old_connections(i).proxy_port, -1) = NVL(p_connection.proxy_port, -1) AND
                        same_boolean(l_old_connections(i).ssl, p_connection.ssl)
                    THEN
                        RETURN TRUE;
                    END IF;
                END LOOP;
            END IF;

            RETURN FALSE;
        END connection_existed;

        PROCEDURE cleanup(p_free_result IN BOOLEAN) IS
        BEGIN
            IF l_response_open THEN
                BEGIN
                    UTL_HTTP.end_response(l_response);
                EXCEPTION
                    WHEN OTHERS THEN
                        NULL;
                END;
                l_response_open := FALSE;
            END IF;

            IF l_settings_saved THEN
                BEGIN
                    UTL_HTTP.get_persistent_conns(l_current_connections);

                    IF l_current_connections.COUNT > 0 THEN
                        FOR i IN 1 .. l_current_connections.COUNT LOOP
                            IF NOT connection_existed(l_current_connections(i)) THEN
                                UTL_HTTP.close_persistent_conn(l_current_connections(i));
                            END IF;
                        END LOOP;
                    END IF;
                EXCEPTION
                    WHEN OTHERS THEN
                        NULL;
                END;
            END IF;

            IF l_context_created THEN
                BEGIN
                    UTL_HTTP.destroy_request_context(l_request_context);
                EXCEPTION
                    WHEN OTHERS THEN
                        NULL;
                END;
                l_context_created := FALSE;
            END IF;

            IF l_settings_saved THEN
                BEGIN
                    UTL_HTTP.set_persistent_conn_support(l_old_persistent, l_old_max_conns);
                    UTL_HTTP.set_transfer_timeout(l_old_timeout);
                    UTL_HTTP.set_response_error_check(l_old_error_check);
                EXCEPTION
                    WHEN OTHERS THEN
                        NULL;
                END;
                l_settings_saved := FALSE;
            END IF;

            IF p_free_result AND DBMS_LOB.istemporary(l_result) = 1 THEN
                DBMS_LOB.freetemporary(l_result);
            END IF;
        END cleanup;

		PROCEDURE prepare_request(
			p_auth_message	IN RAW,
			p_send_body	IN BOOLEAN
		) IS
		BEGIN
			UTL_HTTP.set_follow_redirect(l_request, 0);
			UTL_HTTP.set_cookie_support(l_request, FALSE);
			UTL_HTTP.set_header(l_request, 'Authorization', 'NTLM ' || encode_base64(p_auth_message));

			IF p_accept IS NOT NULL THEN
				UTL_HTTP.set_header(l_request, 'Accept', p_accept);
			END IF;

			IF p_method = 'POST' THEN
				IF p_content_type IS NOT NULL THEN
					UTL_HTTP.set_header(l_request, 'Content-Type', p_content_type);
				END IF;

				IF p_x_request_digest IS NOT NULL THEN
					UTL_HTTP.set_header(l_request, 'X-RequestDigest', p_x_request_digest);
				END IF;

				IF p_if_match IS NOT NULL THEN
					UTL_HTTP.set_header(l_request, 'IF-MATCH', p_if_match);
				END IF;

				IF p_x_http_method IS NOT NULL THEN
					UTL_HTTP.set_header(l_request, 'X-HTTP-Method', p_x_http_method);
				END IF;

				IF NOT p_send_body OR p_body IS NULL THEN
					UTL_HTTP.set_header(l_request, 'Content-Length', '0');
				ELSIF p_send_body THEN
					UTL_HTTP.set_header(l_request, 'Content-Length', TO_CHAR(clob_lengthb(p_body)));
					write_request_body(l_request, p_body);
				END IF;
			END IF;
		END prepare_request;
    BEGIN
		IF p_method IS NULL OR p_method NOT IN ('GET', 'POST') THEN
			raise_application_error(-20001, 'HTTP method must be GET or POST.');
		END IF;

        IF p_url IS NULL OR LENGTHB(p_url) > 4000 OR
            NOT REGEXP_LIKE(
                p_url,
                '^https://([A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\])(:[0-9]+)?([/?]|$)',
                'i'
            ) OR
            REGEXP_LIKE(p_url, '[[:cntrl:]]') OR
            INSTR(p_url, '@') > 0 OR
            INSTR(p_url, '#') > 0
        THEN
            raise_application_error(-20001, 'A valid HTTPS SharePoint URL without user information is required.');
        END IF;

        IF p_username IS NULL OR p_password IS NULL OR p_domain IS NULL OR
            INSTR(p_username, '\') > 0 OR INSTR(p_username, '/') > 0
        THEN
            raise_application_error(-20001, 'Username, password, and domain are required; username must not contain a domain prefix.');
        END IF;

        IF p_wallet_path IS NULL OR NOT (
            LOWER(SUBSTR(p_wallet_path, 1, 5)) = 'file:' OR
            LOWER(p_wallet_path) = 'system:'
        ) THEN
            raise_application_error(-20001, 'Wallet path must use the file: or system: form.');
        END IF;

		IF p_accept IS NOT NULL AND (
			LENGTHB(p_accept) > 4000 OR REGEXP_LIKE(p_accept, '[[:cntrl:]]')
		) THEN
			raise_application_error(-20001, 'Accept header must not contain control characters.');
		END IF;

		IF p_content_type IS NOT NULL AND (
			LENGTHB(p_content_type) > 4000 OR REGEXP_LIKE(p_content_type, '[[:cntrl:]]')
		) THEN
			raise_application_error(-20001, 'Content-Type header must not contain control characters.');
		END IF;

		IF p_x_request_digest IS NOT NULL AND (
			LENGTHB(p_x_request_digest) > 4000 OR REGEXP_LIKE(p_x_request_digest, '[[:cntrl:]]')
		) THEN
			raise_application_error(-20001, 'X-RequestDigest header must not contain control characters.');
		END IF;

		IF p_if_match IS NOT NULL AND (
			LENGTHB(p_if_match) > 4000 OR REGEXP_LIKE(p_if_match, '[[:cntrl:]]')
		) THEN
			raise_application_error(-20001, 'IF-MATCH header must not contain control characters.');
		END IF;

		IF p_x_http_method IS NOT NULL AND (
			LENGTHB(p_x_http_method) > 4000 OR REGEXP_LIKE(p_x_http_method, '[[:cntrl:]]')
		) THEN
			raise_application_error(-20001, 'X-HTTP-Method header must not contain control characters.');
		END IF;

        UTL_HTTP.get_persistent_conn_support(l_old_persistent, l_old_max_conns);
        UTL_HTTP.get_persistent_conns(l_old_connections);
        UTL_HTTP.get_transfer_timeout(l_old_timeout);
        UTL_HTTP.get_response_error_check(l_old_error_check);
        l_settings_saved := TRUE;

        UTL_HTTP.set_persistent_conn_support(TRUE, 1);
        UTL_HTTP.set_transfer_timeout(C_TRANSFER_TIMEOUT);
        UTL_HTTP.set_response_error_check(FALSE);

        l_request_context := UTL_HTTP.create_request_context(
            wallet_path => p_wallet_path,
            wallet_password => p_wallet_pwd,
            enable_cookies => FALSE
        );
        l_context_created := TRUE;
        l_type1 := build_type1();

        l_request := UTL_HTTP.begin_request(
            url => p_url,
            method => p_method,
            http_version => UTL_HTTP.HTTP_VERSION_1_1,
            request_context => l_request_context
        );
        UTL_HTTP.set_persistent_conn_support(l_request, TRUE);
		prepare_request(l_type1, FALSE);

        l_response := UTL_HTTP.get_response(l_request);
        l_response_open := TRUE;

        IF l_response.status_code = UTL_HTTP.HTTP_UNAUTHORIZED THEN
            FOR i IN 1 .. UTL_HTTP.get_header_count(l_response) LOOP
                UTL_HTTP.get_header(l_response, i, l_header_name, l_header_value);

                IF LOWER(l_header_name) = 'www-authenticate' THEN
                    l_type2_token := REGEXP_SUBSTR(
                        l_header_value,
                        'NTLM[[:space:]]+([A-Za-z0-9+/=]+)',
                        1,
                        1,
                        'i',
                        1
                    );
                    EXIT WHEN l_type2_token IS NOT NULL;
                END IF;
            END LOOP;
        END IF;

        l_status_code := l_response.status_code;
        l_reason_phrase := l_response.reason_phrase;
        drain_response(l_response);
        UTL_HTTP.end_response(l_response);
        l_response_open := FALSE;

        IF l_status_code <> UTL_HTTP.HTTP_UNAUTHORIZED OR l_type2_token IS NULL THEN
            raise_application_error(
                -20002,
                'SharePoint did not return an NTLM Type 2 challenge; HTTP ' ||
                l_status_code || ' ' || l_reason_phrase
            );
        END IF;

        parse_type2(l_type2_token, l_type2);
        build_type3(l_type1, l_type2, p_username, p_password, p_domain, l_type3);

        l_request := UTL_HTTP.begin_request(
            url => p_url,
            method => p_method,
            http_version => UTL_HTTP.HTTP_VERSION_1_1,
            request_context => l_request_context
        );
        UTL_HTTP.set_persistent_conn_support(l_request, FALSE);
		prepare_request(l_type3, TRUE);

        l_response := UTL_HTTP.get_response(l_request);
        l_response_open := TRUE;
        l_status_code := l_response.status_code;
        l_reason_phrase := l_response.reason_phrase;
        read_response(l_response, l_result);
        UTL_HTTP.end_response(l_response);
        l_response_open := FALSE;

        IF NOT is_success_response(p_method, l_status_code) THEN
            raise_application_error(
                -20007,
                'SharePoint returned HTTP ' || l_status_code || ' ' || l_reason_phrase ||
                '; body: ' || DBMS_LOB.substr(l_result, 500, 1)
            );
        END IF;

        cleanup(FALSE);
        RETURN l_result;
    EXCEPTION
        WHEN OTHERS THEN
            l_error_code := SQLCODE;

            IF l_error_code = -29273 THEN
                BEGIN
                    l_http_error := UTL_HTTP.get_detailed_sqlerrm;
                EXCEPTION
                    WHEN OTHERS THEN
                        l_http_error := NULL;
                END;

                cleanup(TRUE);

                raise_application_error(
                    -20009,
                    'HTTP request failed' ||
                    CASE WHEN l_http_error IS NOT NULL THEN ': ' || l_http_error ELSE '.' END
                );
            END IF;

            cleanup(TRUE);
            RAISE;
    END make_ntlm_request;

	FUNCTION get_shp_settings RETURN t_shp_settings IS
		l_env		VARCHAR2(8);
		l_settings	t_shp_settings;

		PROCEDURE require_setting(
			p_key	IN VARCHAR2,
			p_value	IN VARCHAR2
		) IS
		BEGIN
			IF p_value IS NULL THEN
				raise_application_error(-20001, 'Missing SharePoint setting: ' || p_key || '.');
			END IF;
		END require_setting;
	BEGIN
		l_env := LCDT.PUB.get_env;

		IF l_env IS NULL THEN
			raise_application_error(-20001, 'LCDT.PUB.get_env returned NULL.');
		END IF;

		l_settings.wallet_path := LCDT.PRV.get_param('WALLET_PATH_' || l_env);
		l_settings.wallet_pwd := LCDT.PRV.get_param('WALLET_PASS_' || l_env);
		l_settings.username := LCDT.PRV.get_param('ILAPEX_USERNAME_' || l_env);
		l_settings.password := LCDT.PRV.get_param('ILAPEX_PASSWORD_' || l_env);

		require_setting('WALLET_PATH_' || l_env, l_settings.wallet_path);
		require_setting('ILAPEX_USERNAME_' || l_env, l_settings.username);
		require_setting('ILAPEX_PASSWORD_' || l_env, l_settings.password);

		RETURN l_settings;
	END get_shp_settings;

	FUNCTION make_get_request(
		p_url			IN VARCHAR2,
		p_username		IN VARCHAR2,
		p_password		IN VARCHAR2,
		p_domain		IN VARCHAR2,
		p_wallet_path	IN VARCHAR2,
		p_wallet_pwd	IN VARCHAR2 DEFAULT NULL,
		p_accept		IN VARCHAR2 DEFAULT 'application/json;odata=verbose'
	) RETURN CLOB IS
	BEGIN
		RETURN make_ntlm_request(
			p_url => p_url,
			p_method => 'GET',
			p_username => p_username,
			p_password => p_password,
			p_domain => p_domain,
			p_wallet_path => p_wallet_path,
			p_wallet_pwd => p_wallet_pwd,
			p_accept => p_accept
		);
	END make_get_request;

	FUNCTION make_post_request(
		p_url			IN VARCHAR2,
		p_username		IN VARCHAR2,
		p_password		IN VARCHAR2,
		p_domain		IN VARCHAR2,
		p_wallet_path	IN VARCHAR2,
		p_wallet_pwd	IN VARCHAR2 DEFAULT NULL,
		p_body			IN CLOB DEFAULT NULL,
		p_content_type	IN VARCHAR2 DEFAULT 'application/json;odata=verbose',
		p_accept		IN VARCHAR2 DEFAULT 'application/json;odata=verbose',
		p_x_request_digest	IN VARCHAR2 DEFAULT NULL,
		p_if_match		IN VARCHAR2 DEFAULT NULL,
		p_x_http_method		IN VARCHAR2 DEFAULT NULL
	) RETURN CLOB IS
	BEGIN
		RETURN make_ntlm_request(
			p_url => p_url,
			p_method => 'POST',
			p_username => p_username,
			p_password => p_password,
			p_domain => p_domain,
			p_wallet_path => p_wallet_path,
			p_wallet_pwd => p_wallet_pwd,
			p_body => p_body,
			p_content_type => p_content_type,
			p_accept => p_accept,
			p_x_request_digest => p_x_request_digest,
			p_if_match => p_if_match,
			p_x_http_method => p_x_http_method
		);
	END make_post_request;

	FUNCTION shp_get(
		p_url	IN VARCHAR2
	) RETURN CLOB IS
		l_settings	t_shp_settings;
	BEGIN
		l_settings := get_shp_settings();

		RETURN make_get_request(
			p_url => p_url,
			p_username => l_settings.username,
			p_password => l_settings.password,
			p_domain => 'GRUPA',
			p_wallet_path => l_settings.wallet_path,
			p_wallet_pwd => l_settings.wallet_pwd
		);
	END shp_get;

	FUNCTION shp_post(
		p_url	IN VARCHAR2,
		p_body	IN CLOB DEFAULT NULL
	) RETURN CLOB IS
		l_settings	t_shp_settings;
	BEGIN
		l_settings := get_shp_settings();

		RETURN make_post_request(
			p_url => p_url,
			p_username => l_settings.username,
			p_password => l_settings.password,
			p_domain => 'GRUPA',
			p_wallet_path => l_settings.wallet_path,
			p_wallet_pwd => l_settings.wallet_pwd,
			p_body => p_body
		);
	END shp_post;

	FUNCTION shp_post_ex(
		p_url			IN VARCHAR2,
		p_body			IN CLOB DEFAULT NULL,
		p_x_request_digest	IN VARCHAR2 DEFAULT NULL,
		p_if_match		IN VARCHAR2 DEFAULT NULL,
		p_x_http_method		IN VARCHAR2 DEFAULT NULL
	) RETURN CLOB IS
		l_settings	t_shp_settings;
	BEGIN
		l_settings := get_shp_settings();

		RETURN make_post_request(
			p_url => p_url,
			p_username => l_settings.username,
			p_password => l_settings.password,
			p_domain => 'GRUPA',
			p_wallet_path => l_settings.wallet_path,
			p_wallet_pwd => l_settings.wallet_pwd,
			p_body => p_body,
			p_x_request_digest => p_x_request_digest,
			p_if_match => p_if_match,
			p_x_http_method => p_x_http_method
		);
	END shp_post_ex;

	PROCEDURE free_temp_clob(p_value IN OUT NOCOPY CLOB) IS
	BEGIN
		IF p_value IS NOT NULL AND DBMS_LOB.istemporary(p_value) = 1 THEN
			DBMS_LOB.freetemporary(p_value);
		END IF;
	EXCEPTION
		WHEN OTHERS THEN
			NULL;
	END free_temp_clob;

	FUNCTION normalize_site_url(p_site_url IN VARCHAR2) RETURN VARCHAR2 IS
		l_site_url	VARCHAR2(4000) := TRIM(p_site_url);
	BEGIN
		IF l_site_url IS NULL THEN
			raise_application_error(-20001, 'SharePoint site URL is required.');
		END IF;

		WHILE SUBSTR(l_site_url, -1) = '/' LOOP
			l_site_url := SUBSTR(l_site_url, 1, LENGTH(l_site_url) - 1);
		END LOOP;

		RETURN l_site_url;
	END normalize_site_url;

	FUNCTION odata_string_literal(p_value IN VARCHAR2) RETURN VARCHAR2 IS
		l_value	VARCHAR2(4000);
	BEGIN
		IF p_value IS NULL OR REGEXP_LIKE(p_value, '[[:cntrl:]]') THEN
			raise_application_error(-20001, 'SharePoint list title is required.');
		END IF;

		l_value := UTL_URL.escape(REPLACE(p_value, '''', ''''''), TRUE, 'AL32UTF8');

		RETURN '''' || l_value || '''';
	END odata_string_literal;

	FUNCTION list_items_endpoint(
		p_site_url	IN VARCHAR2,
		p_list_title	IN VARCHAR2
	) RETURN VARCHAR2 IS
	BEGIN
		RETURN normalize_site_url(p_site_url) ||
			'/_api/web/lists/getbytitle(' || odata_string_literal(p_list_title) || ')/items';
	END list_items_endpoint;

	FUNCTION append_odata_query(
		p_url	IN VARCHAR2,
		p_query	IN VARCHAR2
	) RETURN VARCHAR2 IS
		l_query	VARCHAR2(4000) := TRIM(p_query);
	BEGIN
		IF l_query IS NULL THEN
			RETURN p_url;
		END IF;

		IF LENGTHB(l_query) > 3000 OR REGEXP_LIKE(l_query, '[[:cntrl:]#]') THEN
			raise_application_error(-20001, 'OData query must not contain control characters or URL fragments.');
		END IF;

		IF SUBSTR(l_query, 1, 1) = '?' THEN
			RETURN p_url || l_query;
		ELSIF SUBSTR(l_query, 1, 1) = '&' THEN
			RETURN p_url || '?' || SUBSTR(l_query, 2);
		END IF;

		RETURN p_url || '?' || l_query;
	END append_odata_query;

	FUNCTION http_status_from_error(p_error_detail IN VARCHAR2) RETURN NUMBER IS
		l_status	VARCHAR2(3);
	BEGIN
		l_status := REGEXP_SUBSTR(p_error_detail, 'HTTP[[:space:]]+([0-9]{3})', 1, 1, 'i', 1);
		RETURN TO_NUMBER(l_status);
	EXCEPTION
		WHEN OTHERS THEN
			RETURN NULL;
	END http_status_from_error;

	FUNCTION workflow_success(
		p_operation	IN VARCHAR2,
		p_message	IN VARCHAR2,
		p_item_id	IN NUMBER DEFAULT NULL,
		p_etag		IN VARCHAR2 DEFAULT NULL,
		p_data_json	IN CLOB DEFAULT '{}',
		p_next_url	IN VARCHAR2 DEFAULT NULL
	) RETURN CLOB IS
		l_result	CLOB;
		l_data_json	CLOB := NVL(p_data_json, '{}');
		l_status_code	NUMBER;
	BEGIN
		SELECT JSON_OBJECT(
			'success' VALUE 'true' FORMAT JSON,
			'operation' VALUE p_operation,
			'status_code' VALUE l_status_code,
			'message' VALUE p_message,
			'item_id' VALUE p_item_id,
			'etag' VALUE p_etag,
			'next_url' VALUE p_next_url,
			'data' VALUE l_data_json FORMAT JSON
			NULL ON NULL RETURNING CLOB
		)
		INTO l_result
		FROM DUAL;

		RETURN l_result;
	END workflow_success;

	FUNCTION workflow_error(
		p_operation	IN VARCHAR2,
		p_error_code	IN NUMBER,
		p_error_detail	IN VARCHAR2
	) RETURN CLOB IS
		l_result	CLOB;
		l_status_code	NUMBER;
	BEGIN
		l_status_code := http_status_from_error(p_error_detail);

		SELECT JSON_OBJECT(
			'success' VALUE 'false' FORMAT JSON,
			'operation' VALUE p_operation,
			'status_code' VALUE l_status_code,
			'message' VALUE p_error_detail,
			'error_code' VALUE p_error_code,
			'error_detail' VALUE p_error_detail,
			'data' VALUE '{}' FORMAT JSON
			NULL ON NULL RETURNING CLOB
		)
		INTO l_result
		FROM DUAL;

		RETURN l_result;
	END workflow_error;

	FUNCTION build_item_payload(
		p_fields_json	IN CLOB,
		p_entity_type	IN VARCHAR2
	) RETURN CLOB IS
		l_fields	JSON_OBJECT_T;
		l_patch		CLOB;
		l_payload	CLOB;
	BEGIN
		IF p_fields_json IS NULL THEN
			raise_application_error(-20001, 'SharePoint item fields JSON is required.');
		END IF;

		l_fields := JSON_OBJECT_T.parse(p_fields_json);

		SELECT JSON_OBJECT(
			'__metadata' VALUE JSON_OBJECT('type' VALUE p_entity_type)
			RETURNING CLOB
		)
		INTO l_patch
		FROM DUAL;

		SELECT JSON_MERGEPATCH(p_fields_json, l_patch RETURNING CLOB)
		INTO l_payload
		FROM DUAL;

		RETURN l_payload;
	EXCEPTION
		WHEN OTHERS THEN
			IF SQLCODE BETWEEN -20099 AND -20000 THEN
				RAISE;
			END IF;

			raise_application_error(-20001, 'SharePoint item fields must be a valid JSON object.');
	END build_item_payload;

	FUNCTION get_form_digest(p_site_url IN VARCHAR2) RETURN VARCHAR2 IS
		l_response	CLOB;
		l_digest	VARCHAR2(4000);
	BEGIN
		l_response := shp_post(normalize_site_url(p_site_url) || '/_api/contextinfo');

		SELECT JSON_VALUE(
			l_response,
			'$.d.GetContextWebInformation.FormDigestValue'
			RETURNING VARCHAR2(4000) NULL ON ERROR
		)
		INTO l_digest
		FROM DUAL;

		free_temp_clob(l_response);

		IF l_digest IS NULL THEN
			raise_application_error(-20008, 'SharePoint contextinfo response did not include FormDigestValue.');
		END IF;

		RETURN l_digest;
	EXCEPTION
		WHEN OTHERS THEN
			free_temp_clob(l_response);
			RAISE;
	END get_form_digest;

	FUNCTION get_list_item_entity_type(
		p_site_url	IN VARCHAR2,
		p_list_title	IN VARCHAR2
	) RETURN VARCHAR2 IS
		l_response	CLOB;
		l_entity_type	VARCHAR2(4000);
	BEGIN
		l_response := shp_get(
			normalize_site_url(p_site_url) ||
			'/_api/web/lists/getbytitle(' || odata_string_literal(p_list_title) ||
			')?$select=ListItemEntityTypeFullName'
		);

		SELECT JSON_VALUE(
			l_response,
			'$.d.ListItemEntityTypeFullName'
			RETURNING VARCHAR2(4000) NULL ON ERROR
		)
		INTO l_entity_type
		FROM DUAL;

		free_temp_clob(l_response);

		IF l_entity_type IS NULL THEN
			raise_application_error(-20008, 'SharePoint list metadata response did not include ListItemEntityTypeFullName.');
		END IF;

		RETURN l_entity_type;
	EXCEPTION
		WHEN OTHERS THEN
			free_temp_clob(l_response);
			RAISE;
	END get_list_item_entity_type;

	FUNCTION get_list_item(
		p_site_url	IN VARCHAR2,
		p_list_title	IN VARCHAR2,
		p_item_id	IN NUMBER,
		p_query		IN VARCHAR2 DEFAULT NULL
	) RETURN CLOB IS
		l_response	CLOB;
		l_data		CLOB;
		l_etag		VARCHAR2(4000);
		l_result	CLOB;
	BEGIN
		IF p_item_id IS NULL OR p_item_id < 1 OR p_item_id <> TRUNC(p_item_id) THEN
			raise_application_error(-20001, 'SharePoint item ID must be a positive integer.');
		END IF;

		l_response := shp_get(
			append_odata_query(
				list_items_endpoint(p_site_url, p_list_title) || '(' || TO_CHAR(TRUNC(p_item_id)) || ')',
				p_query
			)
		);

		SELECT
			JSON_QUERY(l_response, '$.d' RETURNING CLOB NULL ON ERROR),
			JSON_VALUE(l_response, '$.d.__metadata.etag' RETURNING VARCHAR2(4000) NULL ON ERROR)
		INTO l_data, l_etag
		FROM DUAL;

		IF l_data IS NULL THEN
			l_data := '{}';
		END IF;

		l_result := workflow_success(
			p_operation => 'get_list_item',
			p_message => 'Item retrieved.',
			p_item_id => p_item_id,
			p_etag => l_etag,
			p_data_json => l_data
		);
		free_temp_clob(l_response);
		free_temp_clob(l_data);

		RETURN l_result;
	EXCEPTION
		WHEN OTHERS THEN
			free_temp_clob(l_response);
			free_temp_clob(l_data);
			RETURN workflow_error('get_list_item', SQLCODE, SQLERRM);
	END get_list_item;

	FUNCTION get_list_items(
		p_site_url	IN VARCHAR2,
		p_list_title	IN VARCHAR2,
		p_query		IN VARCHAR2 DEFAULT NULL
	) RETURN CLOB IS
		l_response	CLOB;
		l_data		CLOB;
		l_next_url	VARCHAR2(4000);
		l_result	CLOB;
	BEGIN
		l_response := shp_get(append_odata_query(list_items_endpoint(p_site_url, p_list_title), p_query));

		SELECT
			JSON_QUERY(l_response, '$.d.results' RETURNING CLOB NULL ON ERROR),
			JSON_VALUE(l_response, '$.d.__next' RETURNING VARCHAR2(4000) NULL ON ERROR)
		INTO l_data, l_next_url
		FROM DUAL;

		IF l_data IS NULL THEN
			l_data := '[]';
		END IF;

		l_result := workflow_success(
			p_operation => 'get_list_items',
			p_message => 'Items retrieved.',
			p_data_json => l_data,
			p_next_url => l_next_url
		);
		free_temp_clob(l_response);
		free_temp_clob(l_data);

		RETURN l_result;
	EXCEPTION
		WHEN OTHERS THEN
			free_temp_clob(l_response);
			free_temp_clob(l_data);
			RETURN workflow_error('get_list_items', SQLCODE, SQLERRM);
	END get_list_items;

	FUNCTION add_list_item(
		p_site_url	IN VARCHAR2,
		p_list_title	IN VARCHAR2,
		p_fields_json	IN CLOB
	) RETURN CLOB IS
		l_digest	VARCHAR2(4000);
		l_entity_type	VARCHAR2(4000);
		l_payload	CLOB;
		l_response	CLOB;
		l_data		CLOB;
		l_item_id	NUMBER;
		l_etag		VARCHAR2(4000);
		l_result	CLOB;
	BEGIN
		l_digest := get_form_digest(p_site_url);
		l_entity_type := get_list_item_entity_type(p_site_url, p_list_title);
		l_payload := build_item_payload(p_fields_json, l_entity_type);
		l_response := shp_post_ex(
			p_url => list_items_endpoint(p_site_url, p_list_title),
			p_body => l_payload,
			p_x_request_digest => l_digest
		);

		SELECT
			JSON_QUERY(l_response, '$.d' RETURNING CLOB NULL ON ERROR),
			NVL(
				JSON_VALUE(l_response, '$.d.Id' RETURNING NUMBER NULL ON ERROR),
				JSON_VALUE(l_response, '$.d.ID' RETURNING NUMBER NULL ON ERROR)
			),
			JSON_VALUE(l_response, '$.d.__metadata.etag' RETURNING VARCHAR2(4000) NULL ON ERROR)
		INTO l_data, l_item_id, l_etag
		FROM DUAL;

		IF l_data IS NULL THEN
			l_data := '{}';
		END IF;

		l_result := workflow_success(
			p_operation => 'add_list_item',
			p_message => 'Item created.',
			p_item_id => l_item_id,
			p_etag => l_etag,
			p_data_json => l_data
		);
		free_temp_clob(l_payload);
		free_temp_clob(l_response);
		free_temp_clob(l_data);

		RETURN l_result;
	EXCEPTION
		WHEN OTHERS THEN
			free_temp_clob(l_payload);
			free_temp_clob(l_response);
			free_temp_clob(l_data);
			RETURN workflow_error('add_list_item', SQLCODE, SQLERRM);
	END add_list_item;

	FUNCTION update_list_item(
		p_site_url	IN VARCHAR2,
		p_list_title	IN VARCHAR2,
		p_item_id	IN NUMBER,
		p_fields_json	IN CLOB,
		p_etag		IN VARCHAR2 DEFAULT '*'
	) RETURN CLOB IS
		l_digest	VARCHAR2(4000);
		l_entity_type	VARCHAR2(4000);
		l_payload	CLOB;
		l_response	CLOB;
		l_result	CLOB;
	BEGIN
		IF p_item_id IS NULL OR p_item_id < 1 OR p_item_id <> TRUNC(p_item_id) THEN
			raise_application_error(-20001, 'SharePoint item ID must be a positive integer.');
		END IF;

		l_digest := get_form_digest(p_site_url);
		l_entity_type := get_list_item_entity_type(p_site_url, p_list_title);
		l_payload := build_item_payload(p_fields_json, l_entity_type);
		l_response := shp_post_ex(
			p_url => list_items_endpoint(p_site_url, p_list_title) || '(' || TO_CHAR(TRUNC(p_item_id)) || ')',
			p_body => l_payload,
			p_x_request_digest => l_digest,
			p_if_match => NVL(p_etag, '*'),
			p_x_http_method => 'MERGE'
		);
		l_result := workflow_success(
			p_operation => 'update_list_item',
			p_message => 'Item updated.',
			p_item_id => p_item_id,
			p_etag => NVL(p_etag, '*'),
			p_data_json => '{}'
		);
		free_temp_clob(l_payload);
		free_temp_clob(l_response);

		RETURN l_result;
	EXCEPTION
		WHEN OTHERS THEN
			free_temp_clob(l_payload);
			free_temp_clob(l_response);
			RETURN workflow_error('update_list_item', SQLCODE, SQLERRM);
	END update_list_item;

END "SHP_API";
/