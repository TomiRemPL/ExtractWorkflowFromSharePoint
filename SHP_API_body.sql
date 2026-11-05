CREATE OR REPLACE PACKAGE BODY "SHP_API" AS

    C_TRANSFER_TIMEOUT	CONSTANT PLS_INTEGER := 60;
    C_READ_CHUNK_SIZE	CONSTANT PLS_INTEGER := 32767;
	C_WRITE_CHUNK_CHARS	CONSTANT PLS_INTEGER := 8191;
    C_MAX_RESPONSE_SIZE	CONSTANT PLS_INTEGER := 10 * 1024 * 1024;
	C_MAX_ATTACHMENT_SIZE	CONSTANT PLS_INTEGER := 100 * 1024 * 1024;

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
				message                        RAW(32767),
				flags                  NUMBER,
				server_challenge       RAW(8),
				target_info            RAW(32767),
				timestamp              RAW(8),
				mic_required           BOOLEAN
		);

	   TYPE t_shp_settings IS RECORD (
			   wallet_path     VARCHAR2(256),
			   wallet_pwd      VARCHAR2(256),
			   username        VARCHAR2(256),
			   password        VARCHAR2(256)
	   );

	FUNCTION raw_append(
		p_left IN RAW,
		p_right        IN RAW
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
		p_value        IN NUMBER,
		p_bytes        IN PLS_INTEGER
	) RETURN RAW IS
		l_value        NUMBER := p_value;
		l_byte         PLS_INTEGER;
		l_hex          VARCHAR2(32767);
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
			l_chunk := DBMS_LOB.substr(p_body, C_WRITE_CHUNK_CHARS, l_offset);
			UTL_HTTP.write_raw(p_request, UTL_I18N.string_to_raw(l_chunk, 'AL32UTF8'));
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
			l_chunk := DBMS_LOB.substr(p_body, C_WRITE_CHUNK_CHARS, l_offset);
			l_total := l_total + UTL_RAW.length(UTL_I18N.string_to_raw(l_chunk, 'AL32UTF8'));
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
			l_content_type	VARCHAR2(32767);
		BEGIN
			UTL_HTTP.set_follow_redirect(l_request, 0);
			UTL_HTTP.set_cookie_support(l_request, FALSE);
			UTL_HTTP.set_header(l_request, 'Authorization', 'NTLM ' || encode_base64(p_auth_message));

			IF p_accept IS NOT NULL THEN
				UTL_HTTP.set_header(l_request, 'Accept', p_accept);
			END IF;

			IF p_method = 'POST' THEN
				IF p_content_type IS NOT NULL THEN
					IF REGEXP_LIKE(p_content_type, ';[[:space:]]*charset[[:space:]]*=', 'i') THEN
						l_content_type := REGEXP_REPLACE(
							p_content_type,
							';[[:space:]]*charset[[:space:]]*=[^;]*',
							';charset=UTF-8', 1, 0, 'i'
						);
					ELSE
						l_content_type := p_content_type || ';charset=UTF-8';
					END IF;
					UTL_HTTP.set_header(l_request, 'Content-Type', l_content_type);
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

	FUNCTION make_ntlm_blob_request(
		p_url			IN VARCHAR2,
		p_method		IN VARCHAR2,
		p_username		IN VARCHAR2,
		p_password		IN VARCHAR2,
		p_domain		IN VARCHAR2,
		p_wallet_path	IN VARCHAR2,
		p_wallet_pwd	IN VARCHAR2,
		p_body			IN BLOB DEFAULT NULL,
		p_content_type	IN VARCHAR2 DEFAULT NULL,
		p_accept		IN VARCHAR2 DEFAULT 'application/octet-stream',
		p_x_request_digest	IN VARCHAR2 DEFAULT NULL,
		p_x_http_method	IN VARCHAR2 DEFAULT NULL
	) RETURN BLOB IS
		l_request			UTL_HTTP.req;
		l_response			UTL_HTTP.resp;
		l_request_context	UTL_HTTP.request_context_key;
		l_type1			RAW(32767);
		l_type2			t_ntlm_type2;
		l_type2_token		VARCHAR2(32767);
		l_type3			RAW(32767);
		l_header_name		VARCHAR2(256);
		l_header_value		VARCHAR2(32767);
		l_result			BLOB;
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

		FUNCTION connection_existed(p_connection IN UTL_HTTP.connection) RETURN BOOLEAN IS
		BEGIN
			IF l_old_connections.COUNT > 0 THEN
				FOR i IN 1 .. l_old_connections.COUNT LOOP
					IF NVL(l_old_connections(i).host, CHR(0)) = NVL(p_connection.host, CHR(0)) AND
						NVL(l_old_connections(i).port, -1) = NVL(p_connection.port, -1) AND
						NVL(l_old_connections(i).proxy_host, CHR(0)) = NVL(p_connection.proxy_host, CHR(0)) AND
						NVL(l_old_connections(i).proxy_port, -1) = NVL(p_connection.proxy_port, -1) AND
						((l_old_connections(i).ssl AND p_connection.ssl) OR
							(NOT l_old_connections(i).ssl AND NOT p_connection.ssl) OR
							(l_old_connections(i).ssl IS NULL AND p_connection.ssl IS NULL))
					THEN
						RETURN TRUE;
					END IF;
				END LOOP;
			END IF;
			RETURN FALSE;
		END connection_existed;

		PROCEDURE drain_binary_response IS
			l_chunk RAW(32767);
		BEGIN
			BEGIN
				LOOP
					UTL_HTTP.read_raw(l_response, l_chunk, C_READ_CHUNK_SIZE);
				END LOOP;
			EXCEPTION
				WHEN UTL_HTTP.end_of_body THEN
					NULL;
			END;
		END drain_binary_response;

		PROCEDURE read_binary_response IS
			l_chunk	RAW(32767);
			l_total	PLS_INTEGER := 0;
		BEGIN
			DBMS_LOB.createtemporary(l_result, TRUE, DBMS_LOB.SESSION);
			BEGIN
				LOOP
					UTL_HTTP.read_raw(l_response, l_chunk, C_READ_CHUNK_SIZE);
					l_total := l_total + UTL_RAW.length(l_chunk);
					IF l_total > C_MAX_ATTACHMENT_SIZE THEN
						raise_application_error(-20005, 'SharePoint attachment exceeds 100 MiB.');
					END IF;
					DBMS_LOB.writeappend(l_result, UTL_RAW.length(l_chunk), l_chunk);
				END LOOP;
			EXCEPTION
				WHEN UTL_HTTP.end_of_body THEN
					NULL;
			END;
		END read_binary_response;

		PROCEDURE write_binary_request IS
			l_offset	PLS_INTEGER := 1;
			l_length	PLS_INTEGER;
			l_chunk		RAW(32767);
		BEGIN
			IF p_body IS NULL THEN
				UTL_HTTP.set_header(l_request, 'Content-Length', '0');
				RETURN;
			END IF;

			l_length := DBMS_LOB.getlength(p_body);
			IF l_length > C_MAX_ATTACHMENT_SIZE THEN
				raise_application_error(-20005, 'SharePoint attachment exceeds 100 MiB.');
			END IF;
			UTL_HTTP.set_header(l_request, 'Content-Length', TO_CHAR(l_length, 'FM9999999999999999990'));
			WHILE l_offset <= l_length LOOP
				l_chunk := DBMS_LOB.substr(p_body, C_READ_CHUNK_SIZE, l_offset);
				UTL_HTTP.write_raw(l_request, l_chunk);
				l_offset := l_offset + UTL_RAW.length(l_chunk);
			END LOOP;
		END write_binary_request;

		PROCEDURE prepare_request(p_auth_message IN RAW, p_send_body IN BOOLEAN) IS
		BEGIN
			UTL_HTTP.set_follow_redirect(l_request, 0);
			UTL_HTTP.set_cookie_support(l_request, FALSE);
			UTL_HTTP.set_header(l_request, 'Authorization', 'NTLM ' || encode_base64(p_auth_message));
			IF p_accept IS NOT NULL THEN
				UTL_HTTP.set_header(l_request, 'Accept', p_accept);
			END IF;

			IF p_method = 'POST' THEN
				UTL_HTTP.set_header(l_request, 'Content-Type', p_content_type);
				IF p_x_request_digest IS NOT NULL THEN
					UTL_HTTP.set_header(l_request, 'X-RequestDigest', p_x_request_digest);
				END IF;
				IF p_x_http_method IS NOT NULL THEN
					UTL_HTTP.set_header(l_request, 'X-HTTP-Method', p_x_http_method);
				END IF;
				IF p_send_body THEN
					write_binary_request;
				ELSE
					UTL_HTTP.set_header(l_request, 'Content-Length', '0');
				END IF;
			END IF;
		END prepare_request;

		PROCEDURE cleanup(p_free_result IN BOOLEAN) IS
		BEGIN
			IF l_response_open THEN
				BEGIN
					UTL_HTTP.end_response(l_response);
				EXCEPTION
					WHEN OTHERS THEN NULL;
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
						APEX_DEBUG.error('SHP_API.make_ntlm_blob_request connection cleanup failed: %s', SQLERRM);
				END;
			END IF;
			IF l_context_created THEN
				BEGIN
					UTL_HTTP.destroy_request_context(l_request_context);
				EXCEPTION
					WHEN OTHERS THEN NULL;
				END;
				l_context_created := FALSE;
			END IF;
			IF l_settings_saved THEN
				BEGIN
					UTL_HTTP.set_persistent_conn_support(l_old_persistent, l_old_max_conns);
					UTL_HTTP.set_transfer_timeout(l_old_timeout);
					UTL_HTTP.set_response_error_check(l_old_error_check);
				EXCEPTION
					WHEN OTHERS THEN NULL;
				END;
				l_settings_saved := FALSE;
			END IF;
			IF p_free_result AND l_result IS NOT NULL AND DBMS_LOB.istemporary(l_result) = 1 THEN
				DBMS_LOB.freetemporary(l_result);
			END IF;
		END cleanup;
	BEGIN
		IF p_method IS NULL OR p_method NOT IN ('GET', 'POST') OR
			p_url IS NULL OR LENGTHB(p_url) > 4000 OR
			NOT REGEXP_LIKE(
				p_url,
				'^https://([A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\])(:[0-9]+)?([/?]|$)',
				'i'
			) OR REGEXP_LIKE(p_url, '[[:cntrl:]]') OR
			INSTR(p_url, '@') > 0 OR INSTR(p_url, '#') > 0
		THEN
			raise_application_error(-20001, 'A valid HTTPS SharePoint URL and GET or POST method are required.');
		END IF;
		IF p_username IS NULL OR p_password IS NULL OR p_domain IS NULL OR
			INSTR(p_username, '\') > 0 OR INSTR(p_username, '/') > 0
		THEN
			raise_application_error(-20001, 'Username, password, and domain are required; username must not contain a domain prefix.');
		END IF;
		IF p_wallet_path IS NULL OR NOT (
			LOWER(SUBSTR(p_wallet_path, 1, 5)) = 'file:' OR LOWER(p_wallet_path) = 'system:'
		) THEN
			raise_application_error(-20001, 'Wallet path must use the file: or system: form.');
		END IF;
		IF p_method = 'POST' AND (p_body IS NULL OR p_content_type IS NULL) THEN
			raise_application_error(-20001, 'A binary request body and content type are required for POST.');
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

		IF p_x_http_method IS NOT NULL AND (p_method <> 'POST' OR p_x_http_method <> 'PUT') THEN
			raise_application_error(-20001, 'Binary HTTP method override must be PUT with POST.');
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
			url => p_url, method => p_method,
			http_version => UTL_HTTP.HTTP_VERSION_1_1,
			request_context => l_request_context
		);
		-- NTLM Type 1 and Type 3 must use the same connection.
		UTL_HTTP.set_persistent_conn_support(l_request, TRUE);
		prepare_request(l_type1, FALSE);
		l_response := UTL_HTTP.get_response(l_request);
		l_response_open := TRUE;
		IF l_response.status_code = UTL_HTTP.HTTP_UNAUTHORIZED THEN
			FOR i IN 1 .. UTL_HTTP.get_header_count(l_response) LOOP
				UTL_HTTP.get_header(l_response, i, l_header_name, l_header_value);
				IF LOWER(l_header_name) = 'www-authenticate' THEN
					l_type2_token := REGEXP_SUBSTR(
						l_header_value, 'NTLM[[:space:]]+([A-Za-z0-9+/=]+)', 1, 1, 'i', 1
					);
					EXIT WHEN l_type2_token IS NOT NULL;
				END IF;
			END LOOP;
		END IF;
		l_status_code := l_response.status_code;
		l_reason_phrase := l_response.reason_phrase;
		drain_binary_response;
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
			url => p_url, method => p_method,
			http_version => UTL_HTTP.HTTP_VERSION_1_1,
			request_context => l_request_context
		);
		UTL_HTTP.set_persistent_conn_support(l_request, FALSE);
		prepare_request(l_type3, TRUE);
		l_response := UTL_HTTP.get_response(l_request);
		l_response_open := TRUE;
		l_status_code := l_response.status_code;
		l_reason_phrase := l_response.reason_phrase;
		IF p_method = 'GET' AND l_status_code = UTL_HTTP.HTTP_OK THEN
			read_binary_response;
		ELSE
			drain_binary_response;
		END IF;
		UTL_HTTP.end_response(l_response);
		l_response_open := FALSE;

		IF (p_method = 'GET' AND l_status_code <> UTL_HTTP.HTTP_OK) OR
			(p_method = 'POST' AND l_status_code NOT IN (200, 201, 202, 204))
		THEN
			raise_application_error(
				-20007, 'SharePoint returned HTTP ' || l_status_code || ' ' || l_reason_phrase || '.'
			);
		END IF;
		cleanup(FALSE);
		RETURN l_result;
	EXCEPTION
		WHEN OTHERS THEN
			cleanup(TRUE);
			RAISE;
	END make_ntlm_blob_request;

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

	FUNCTION ensure_user_id(
		p_site_url	IN VARCHAR2,
		p_login_name	IN VARCHAR2
	) RETURN NUMBER IS
		l_login_name	VARCHAR2(32767);
		l_site_url	VARCHAR2(4000);
		l_digest	VARCHAR2(4000);
		l_payload	CLOB;
		l_response	CLOB;
		l_object	JSON_OBJECT_T;
		l_user		JSON_OBJECT_T;
		l_value		JSON_ELEMENT_T;
		l_user_id	NUMBER;
		l_principal_type	NUMBER;
	BEGIN
		l_login_name := TRIM(p_login_name);
		IF l_login_name IS NULL OR LENGTHB(l_login_name) > 4000
			OR REGEXP_LIKE(l_login_name, '[[:cntrl:]]') THEN
			raise_application_error(-20001, 'SharePoint claims login is required, limited to 4000 bytes, without control characters.');
		END IF;
		l_site_url := normalize_site_url(p_site_url);
		l_digest := get_form_digest(l_site_url);
		l_object := JSON_OBJECT_T();
		l_object.put('logonName', l_login_name);
		l_payload := l_object.to_clob();
		l_response := shp_post_ex(
			p_url => l_site_url || '/_api/web/ensureuser',
			p_body => l_payload,
			p_x_request_digest => l_digest
		);

		BEGIN
			l_object := JSON_OBJECT_T.parse(l_response);
			l_object.on_error(1);
			l_user := l_object.get_object('d');
			IF l_user IS NULL THEN
				raise_application_error(-20008, 'SharePoint user response is missing the d object.');
			END IF;
			l_user.on_error(1);
			l_value := l_user.get('Id');
			IF l_value IS NULL OR NOT l_value.is_number() THEN
				raise_application_error(-20008, 'SharePoint user response has an invalid Id.');
			END IF;
			l_user_id := l_user.get_number('Id');
			IF l_user_id IS NULL OR l_user_id < 1 OR l_user_id <> TRUNC(l_user_id)
				OR l_user_id > 2147483647 THEN
				raise_application_error(-20008, 'SharePoint user response has an invalid Id.');
			END IF;
			l_value := l_user.get('PrincipalType');
			IF l_value IS NULL OR NOT l_value.is_number() THEN
				raise_application_error(-20008, 'SharePoint user response has an invalid PrincipalType.');
			END IF;
			l_principal_type := l_user.get_number('PrincipalType');
		EXCEPTION
			WHEN OTHERS THEN
				IF SQLCODE = -20008 THEN
					RAISE;
				END IF;
				raise_application_error(-20008, 'SharePoint returned a malformed user response.');
		END;

		IF l_principal_type <> 1 THEN
			raise_application_error(-20001, 'Claims login must resolve to an individual user, not a group.');
		END IF;
		free_temp_clob(l_payload);
		free_temp_clob(l_response);
		RETURN l_user_id;
	EXCEPTION
		WHEN OTHERS THEN
			free_temp_clob(l_payload);
			free_temp_clob(l_response);
			RAISE;
	END ensure_user_id;

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
		p_query		IN VARCHAR2 DEFAULT NULL,
		p_raise_on_error	IN VARCHAR2 DEFAULT 'Y'
	) RETURN CLOB IS
		l_response	CLOB;
		l_data		CLOB;
		l_etag		VARCHAR2(4000);
		l_result	CLOB;
		l_raise_on_error	VARCHAR2(32767);
	BEGIN
		l_raise_on_error := NVL(UPPER(TRIM(p_raise_on_error)), 'N');
		IF l_raise_on_error NOT IN ('Y', 'N') THEN
			raise_application_error(-20001, 'p_raise_on_error must be Y or N.');
		END IF;

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
			IF l_raise_on_error = 'Y' THEN
				RAISE;
			END IF;
			RETURN workflow_error('get_list_item', SQLCODE, SQLERRM);
	END get_list_item;

	FUNCTION get_list_items(
		p_site_url	IN VARCHAR2,
		p_list_title	IN VARCHAR2,
		p_query		IN VARCHAR2 DEFAULT NULL,
		p_raise_on_error	IN VARCHAR2 DEFAULT 'Y'
	) RETURN CLOB IS
		l_response	CLOB;
		l_data		CLOB;
		l_next_url	VARCHAR2(4000);
		l_result	CLOB;
		l_raise_on_error	VARCHAR2(32767);
	BEGIN
		l_raise_on_error := NVL(UPPER(TRIM(p_raise_on_error)), 'N');
		IF l_raise_on_error NOT IN ('Y', 'N') THEN
			raise_application_error(-20001, 'p_raise_on_error must be Y or N.');
		END IF;

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
			IF l_raise_on_error = 'Y' THEN
				RAISE;
			END IF;
			RETURN workflow_error('get_list_items', SQLCODE, SQLERRM);
	END get_list_items;

	FUNCTION add_list_item(
		p_site_url	IN VARCHAR2,
		p_list_title	IN VARCHAR2,
		p_fields_json	IN CLOB,
		p_raise_on_error	IN VARCHAR2 DEFAULT 'Y'
	) RETURN CLOB IS
		l_digest	VARCHAR2(4000);
		l_entity_type	VARCHAR2(4000);
		l_payload	CLOB;
		l_response	CLOB;
		l_data		CLOB;
		l_item_id	NUMBER;
		l_etag		VARCHAR2(4000);
		l_result	CLOB;
		l_raise_on_error	VARCHAR2(32767);
	BEGIN
		l_raise_on_error := NVL(UPPER(TRIM(p_raise_on_error)), 'N');
		IF l_raise_on_error NOT IN ('Y', 'N') THEN
			raise_application_error(-20001, 'p_raise_on_error must be Y or N.');
		END IF;

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
			IF l_raise_on_error = 'Y' THEN
				RAISE;
			END IF;
			RETURN workflow_error('add_list_item', SQLCODE, SQLERRM);
	END add_list_item;

	FUNCTION update_list_item(
		p_site_url	IN VARCHAR2,
		p_list_title	IN VARCHAR2,
		p_item_id	IN NUMBER,
		p_fields_json	IN CLOB,
		p_etag		IN VARCHAR2 DEFAULT '*',
		p_raise_on_error	IN VARCHAR2 DEFAULT 'Y'
	) RETURN CLOB IS
		l_digest	VARCHAR2(4000);
		l_entity_type	VARCHAR2(4000);
		l_payload	CLOB;
		l_response	CLOB;
		l_result	CLOB;
		l_raise_on_error	VARCHAR2(32767);
	BEGIN
		l_raise_on_error := NVL(UPPER(TRIM(p_raise_on_error)), 'N');
		IF l_raise_on_error NOT IN ('Y', 'N') THEN
			raise_application_error(-20001, 'p_raise_on_error must be Y or N.');
		END IF;

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
			IF l_raise_on_error = 'Y' THEN
				RAISE;
			END IF;
			RETURN workflow_error('update_list_item', SQLCODE, SQLERRM);
	END update_list_item;

	FUNCTION copy_list_item_attachments(
		p_source_site_url	IN VARCHAR2,
		p_source_list_title	IN VARCHAR2,
		p_source_item_id	IN NUMBER,
		p_target_site_url	IN VARCHAR2,
		p_target_list_title	IN VARCHAR2,
		p_target_item_id	IN NUMBER,
		p_raise_on_error	IN VARCHAR2 DEFAULT 'Y'
	) RETURN CLOB IS
		TYPE t_attachment_names IS TABLE OF VARCHAR2(4000) INDEX BY VARCHAR2(255);
		l_settings		t_shp_settings;
		l_response		CLOB;
		l_target_response	CLOB;
		l_attachment	BLOB;
		l_digest		VARCHAR2(4000);
		l_result		CLOB;
		l_data_clob		CLOB;
		l_upload_result	BLOB;
		l_raise_on_error	VARCHAR2(32767);
		l_file_name		VARCHAR2(4000);
		l_target_url	VARCHAR2(4000);
		l_x_http_method	VARCHAR2(3);
		l_stage			VARCHAR2(100) := 'validate_input';
		l_copied_count	PLS_INTEGER := 0;
		l_source_attachment_count PLS_INTEGER;
		l_target_names	t_attachment_names;
		l_files			JSON_ARRAY_T := JSON_ARRAY_T();
		l_data			JSON_OBJECT_T;
		l_error_object	JSON_OBJECT_T;
		l_error_code	NUMBER;
		l_error_detail	VARCHAR2(4000);
	BEGIN
		l_raise_on_error := NVL(UPPER(TRIM(p_raise_on_error)), 'N');
		IF l_raise_on_error NOT IN ('Y', 'N') THEN
			raise_application_error(-20001, 'p_raise_on_error must be Y or N.');
		END IF;

		IF p_source_item_id IS NULL OR p_source_item_id < 1 OR
			p_source_item_id <> TRUNC(p_source_item_id) OR p_source_item_id > 2147483647 OR
			p_target_item_id IS NULL OR p_target_item_id < 1 OR
			p_target_item_id <> TRUNC(p_target_item_id) OR p_target_item_id > 2147483647
		THEN
			raise_application_error(-20001, 'Source and target item IDs must be positive 32-bit integers.');
		END IF;

		l_stage := 'list_source_attachments';
		l_response := shp_get(
			list_items_endpoint(p_source_site_url, p_source_list_title) ||
			'(' || TO_CHAR(TRUNC(p_source_item_id)) || ')/AttachmentFiles?$select=FileName'
		);
		DECLARE
			l_attachment_list	CLOB;
		BEGIN
			SELECT JSON_QUERY(l_response, '$.d.results' RETURNING CLOB NULL ON ERROR)
			INTO l_attachment_list
			FROM DUAL;
			IF l_attachment_list IS NULL THEN
				raise_application_error(-20008, 'SharePoint attachment response did not contain an attachment list.');
			END IF;
			free_temp_clob(l_attachment_list);
		EXCEPTION
			WHEN OTHERS THEN
				free_temp_clob(l_attachment_list);
				RAISE;
		END;

		SELECT COUNT(*)
		INTO l_source_attachment_count
		FROM JSON_TABLE(
			l_response,
			'$.d.results[*]'
			COLUMNS (file_name VARCHAR2(4000) PATH '$.FileName' NULL ON ERROR)
		);
		IF l_source_attachment_count > 0 THEN
			l_stage := 'list_target_attachments';
			l_target_response := shp_get(
				list_items_endpoint(p_target_site_url, p_target_list_title) ||
				'(' || TO_CHAR(TRUNC(p_target_item_id)) || ')/AttachmentFiles?$select=FileName'
			);
			DECLARE
				l_target_attachment_list CLOB;
			BEGIN
				SELECT JSON_QUERY(l_target_response, '$.d.results' RETURNING CLOB NULL ON ERROR)
				INTO l_target_attachment_list
				FROM DUAL;
				IF l_target_attachment_list IS NULL THEN
					raise_application_error(-20008, 'SharePoint response did not contain the target attachment list.');
				END IF;
				free_temp_clob(l_target_attachment_list);
			EXCEPTION
				WHEN OTHERS THEN
					free_temp_clob(l_target_attachment_list);
					RAISE;
			END;
			FOR l_target_file IN (
				SELECT file_name
				FROM JSON_TABLE(
					l_target_response,
					'$.d.results[*]'
					COLUMNS (file_name VARCHAR2(4000) PATH '$.FileName' NULL ON ERROR)
				)
			) LOOP
				IF l_target_file.file_name IS NULL OR LENGTHB(l_target_file.file_name) > 255 THEN
					raise_application_error(-20008, 'SharePoint returned an invalid target attachment file name.');
				END IF;
				l_target_names(UPPER(l_target_file.file_name)) := l_target_file.file_name;
			END LOOP;
		END IF;

		l_settings := get_shp_settings();
		FOR l_file IN (
			SELECT file_name
			FROM JSON_TABLE(
				l_response,
				'$.d.results[*]'
				COLUMNS (file_name VARCHAR2(4000) PATH '$.FileName' NULL ON ERROR)
			)
		) LOOP
			l_file_name := l_file.file_name;
			l_stage := 'validate_attachment_name';
			IF l_file_name IS NULL OR LENGTHB(l_file_name) > 255 OR
				REGEXP_LIKE(l_file_name, '[[:cntrl:]]') OR
				INSTR(l_file_name, '/') > 0 OR INSTR(l_file_name, '\') > 0
			THEN
				raise_application_error(-20008, 'SharePoint returned an invalid attachment file name.');
			END IF;
			IF l_digest IS NULL THEN
				l_stage := 'get_target_digest';
				l_digest := get_form_digest(p_target_site_url);
			END IF;

			l_stage := 'download_attachment';
			l_attachment := make_ntlm_blob_request(
				p_url => normalize_site_url(p_source_site_url) ||
					'/_api/web/lists/getbytitle(' || odata_string_literal(p_source_list_title) ||
					')/items(' || TO_CHAR(TRUNC(p_source_item_id)) || ')/AttachmentFiles(' ||
					odata_string_literal(l_file_name) || ')/$value',
				p_method => 'GET',
				p_username => l_settings.username,
				p_password => l_settings.password,
				p_domain => 'GRUPA',
				p_wallet_path => l_settings.wallet_path,
				p_wallet_pwd => l_settings.wallet_pwd
			);

			l_target_url := list_items_endpoint(p_target_site_url, p_target_list_title) ||
				'(' || TO_CHAR(TRUNC(p_target_item_id)) || ')/AttachmentFiles';
			l_x_http_method := NULL;
			IF l_target_names.EXISTS(UPPER(l_file_name)) THEN
				l_stage := 'overwrite_attachment';
				l_target_url := l_target_url || '(' ||
					odata_string_literal(l_target_names(UPPER(l_file_name))) || ')/$value';
				l_x_http_method := 'PUT';
			ELSE
				l_stage := 'upload_attachment';
				l_target_url := l_target_url || '/add(FileName=' || odata_string_literal(l_file_name) || ')';
			END IF;
			l_upload_result := make_ntlm_blob_request(
				p_url => l_target_url,
				p_method => 'POST',
				p_username => l_settings.username,
				p_password => l_settings.password,
				p_domain => 'GRUPA',
				p_wallet_path => l_settings.wallet_path,
				p_wallet_pwd => l_settings.wallet_pwd,
				p_body => l_attachment,
				p_content_type => 'application/octet-stream',
				p_accept => 'application/json;odata=verbose',
				p_x_request_digest => l_digest,
				p_x_http_method => l_x_http_method
			);
			IF NOT l_target_names.EXISTS(UPPER(l_file_name)) THEN
				l_target_names(UPPER(l_file_name)) := l_file_name;
			END IF;
			IF DBMS_LOB.istemporary(l_attachment) = 1 THEN
				DBMS_LOB.freetemporary(l_attachment);
			END IF;
			IF l_upload_result IS NOT NULL AND DBMS_LOB.istemporary(l_upload_result) = 1 THEN
				DBMS_LOB.freetemporary(l_upload_result);
			END IF;
			l_attachment := NULL;
			l_upload_result := NULL;
			l_files.append(l_file_name);
			l_copied_count := l_copied_count + 1;
		END LOOP;

		l_data := JSON_OBJECT_T();
		l_data.put('copied_count', l_copied_count);
		l_data.put('files', l_files);
		l_data_clob := l_data.to_clob();
		l_result := workflow_success(
			p_operation => 'copy_list_item_attachments',
			p_message => 'List item attachments copied.',
			p_item_id => p_target_item_id,
			p_data_json => l_data_clob
		);
		free_temp_clob(l_response);
		free_temp_clob(l_target_response);
		free_temp_clob(l_data_clob);
		RETURN l_result;
	EXCEPTION
		WHEN OTHERS THEN
			l_error_code := SQLCODE;
			l_error_detail := SQLERRM;
			free_temp_clob(l_response);
			free_temp_clob(l_target_response);
			free_temp_clob(l_data_clob);
			IF l_attachment IS NOT NULL AND DBMS_LOB.istemporary(l_attachment) = 1 THEN
				DBMS_LOB.freetemporary(l_attachment);
			END IF;
			IF l_upload_result IS NOT NULL AND DBMS_LOB.istemporary(l_upload_result) = 1 THEN
				DBMS_LOB.freetemporary(l_upload_result);
			END IF;
			IF l_raise_on_error = 'Y' THEN
				BEGIN
					APEX_DEBUG.error(
						'SHP_API.copy_list_item_attachments stage=%s copied=%s file=%s code=%s',
						l_stage, TO_CHAR(l_copied_count), l_file_name, TO_CHAR(l_error_code)
					);
				EXCEPTION
					WHEN OTHERS THEN NULL;
				END;
				RAISE;
			END IF;

			l_result := workflow_error('copy_list_item_attachments', l_error_code, l_error_detail);
			l_error_object := JSON_OBJECT_T.parse(l_result);
			free_temp_clob(l_result);
			l_data := JSON_OBJECT_T();
			l_data.put('stage', l_stage);
			l_data.put('copied_count', l_copied_count);
			l_data.put('files', l_files);
			l_error_object.put('item_id', p_target_item_id);
			l_error_object.put('data', l_data);
			RETURN l_error_object.to_clob();
	END copy_list_item_attachments;

	FUNCTION set_list_item_permissions(
		p_site_url	IN VARCHAR2,
		p_list_title	IN VARCHAR2,
		p_item_id	IN NUMBER,
		p_permissions_json IN CLOB,
		p_raise_on_error IN VARCHAR2 DEFAULT 'Y'
	) RETURN CLOB IS
		TYPE t_permission IS RECORD (
			operation VARCHAR2(20),
			principal_type VARCHAR2(30),
			principal_name VARCHAR2(4000),
			principal_id NUMBER,
			role_name VARCHAR2(4000),
			role_id NUMBER,
			role_manages_permissions BOOLEAN,
			contains_executing_account BOOLEAN,
			unchanged_self_group BOOLEAN,
			duplicate_entry BOOLEAN
		);
		TYPE t_permissions IS TABLE OF t_permission INDEX BY PLS_INTEGER;
		l_permissions t_permissions;
		l_input JSON_ARRAY_T;
		l_entry JSON_OBJECT_T;
		l_keys JSON_KEY_LIST;
		l_element JSON_ELEMENT_T;
		l_response CLOB;
		l_payload CLOB;
		l_data_clob CLOB;
		l_result CLOB;
		l_web_url VARCHAR2(4000);
		l_item_url VARCHAR2(4000);
		l_digest VARCHAR2(4000);
		l_digest_time DATE;
		l_raise_on_error VARCHAR2(32767);
		l_stage VARCHAR2(100) := 'validate_input';
		l_operation VARCHAR2(20);
		l_current_index PLS_INTEGER;
		l_current_user_id NUMBER;
		l_is_site_admin BOOLEAN;
		l_has_unique_assignments BOOLEAN;
		l_requires_unique_scope BOOLEAN := FALSE;
		l_inheritance_broken BOOLEAN := FALSE;
		l_partial_changes BOOLEAN := FALSE;
		l_write_uncertain BOOLEAN := FALSE;
		l_completed_count PLS_INTEGER := 0;
		l_last_mutation VARCHAR2(100);
		l_user_registration_attempted BOOLEAN := FALSE;
		l_results JSON_ARRAY_T := JSON_ARRAY_T();
		l_progress JSON_OBJECT_T;
		l_report JSON_OBJECT_T;
		l_object JSON_OBJECT_T;
		l_requested_role JSON_OBJECT_T;
		l_item JSON_OBJECT_T;
		l_bindings JSON_ARRAY_T;
		l_original_roles JSON_ARRAY_T;
		l_error_code NUMBER;
		l_error_detail VARCHAR2(4000);

		FUNCTION number_literal(p_value IN NUMBER) RETURN VARCHAR2 IS
		BEGIN
			RETURN TO_CHAR(p_value, 'TM9', 'NLS_NUMERIC_CHARACTERS=''.,''');
		END number_literal;

		PROCEDURE require_id(p_value IN NUMBER, p_label IN VARCHAR2) IS
		BEGIN
			IF p_value IS NULL OR p_value < 1 OR p_value <> TRUNC(p_value)
				OR p_value > 2147483647 THEN
				raise_application_error(-20001, p_label || ' must be a positive 32-bit integer.');
			END IF;
		END require_id;

		FUNCTION input_text(p_object IN JSON_OBJECT_T, p_key IN VARCHAR2) RETURN VARCHAR2 IS
			l_value JSON_ELEMENT_T;
			l_text VARCHAR2(4000);
		BEGIN
			IF NOT p_object.has(p_key) THEN
				RETURN NULL;
			END IF;
			l_value := p_object.get(p_key);
			IF NOT l_value.is_string() THEN
				raise_application_error(-20001, p_key || ' must be a nonempty JSON string.');
			END IF;
			l_text := TRIM(p_object.get_string(p_key));
			IF l_text IS NULL OR REGEXP_LIKE(l_text, '[[:cntrl:]]') THEN
				raise_application_error(-20001, p_key || ' must be a nonempty string without control characters.');
			END IF;
			RETURN l_text;
		END input_text;

		FUNCTION input_id(p_object IN JSON_OBJECT_T, p_key IN VARCHAR2) RETURN NUMBER IS
			l_value JSON_ELEMENT_T;
			l_id NUMBER;
		BEGIN
			IF NOT p_object.has(p_key) THEN
				RETURN NULL;
			END IF;
			l_value := p_object.get(p_key);
			IF NOT l_value.is_number() THEN
				raise_application_error(-20001, p_key || ' must be a JSON number.');
			END IF;
			l_id := p_object.get_number(p_key);
			require_id(l_id, p_key);
			RETURN l_id;
		END input_id;

		FUNCTION response_data RETURN JSON_OBJECT_T IS
			l_root JSON_OBJECT_T;
			l_data JSON_OBJECT_T;
		BEGIN
			l_root := JSON_OBJECT_T.parse(l_response);
			l_root.on_error(1);
			l_data := l_root.get_object('d');
			IF l_data IS NULL THEN
				raise_application_error(-20008, 'SharePoint response is missing the d object.');
			END IF;
			l_data.on_error(1);
			free_temp_clob(l_response);
			RETURN l_data;
		END response_data;

		FUNCTION read_object(p_url IN VARCHAR2) RETURN JSON_OBJECT_T IS
		BEGIN
			free_temp_clob(l_response);
			l_response := shp_get(p_url);
			RETURN response_data();
		END read_object;

		FUNCTION required_response_id(p_object IN JSON_OBJECT_T) RETURN NUMBER IS
			l_id NUMBER;
		BEGIN
			l_id := p_object.get_number('Id');
			IF l_id IS NULL OR l_id < 1 OR l_id <> TRUNC(l_id) OR l_id > 2147483647 THEN
				raise_application_error(-20008, 'SharePoint response has an invalid Id.');
			END IF;
			RETURN l_id;
		END required_response_id;

		FUNCTION response_boolean(p_object IN JSON_OBJECT_T, p_key IN VARCHAR2) RETURN BOOLEAN IS
			l_value JSON_ELEMENT_T;
		BEGIN
			IF NOT p_object.has(p_key) THEN
				raise_application_error(-20008, 'SharePoint response is missing ' || p_key || '.');
			END IF;
			l_value := p_object.get(p_key);
			IF NOT l_value.is_boolean() THEN
				raise_application_error(-20008, 'SharePoint response has an invalid ' || p_key || '.');
			END IF;
			RETURN p_object.get_boolean(p_key);
		END response_boolean;

		FUNCTION response_number(p_object IN JSON_OBJECT_T, p_key IN VARCHAR2) RETURN NUMBER IS
			l_value JSON_ELEMENT_T;
		BEGIN
			IF NOT p_object.has(p_key) THEN
				raise_application_error(-20008, 'SharePoint response is missing ' || p_key || '.');
			END IF;
			l_value := p_object.get(p_key);
			IF NOT l_value.is_number() THEN
				raise_application_error(-20008, 'SharePoint response has an invalid ' || p_key || '.');
			END IF;
			RETURN p_object.get_number(p_key);
		END response_number;

		PROCEDURE ensure_digest IS
		BEGIN
			IF l_digest IS NULL OR l_digest_time < SYSDATE - 5 / 1440 THEN
				l_digest := get_form_digest(p_site_url);
				l_digest_time := SYSDATE;
			END IF;
		END ensure_digest;

		PROCEDURE mutate(p_url IN VARCHAR2, p_method IN VARCHAR2 DEFAULT NULL) IS
		BEGIN
			ensure_digest();
			l_write_uncertain := TRUE;
			l_response := shp_post_ex(
				p_url => p_url,
				p_x_request_digest => l_digest,
				p_x_http_method => p_method
			);
			l_partial_changes := TRUE;
			l_last_mutation := l_stage;
			l_write_uncertain := FALSE;
			free_temp_clob(l_response);
		END mutate;

		FUNCTION collection_results(p_object IN JSON_OBJECT_T) RETURN JSON_ARRAY_T IS
			l_safe_object JSON_OBJECT_T := p_object.clone();
			l_array JSON_ARRAY_T;
			l_value JSON_ELEMENT_T;
		BEGIN
			l_safe_object.on_error(0);
			IF l_safe_object.has('__next') THEN
				raise_application_error(-20008, 'Permission lookup was paginated; refusing an incomplete ACL snapshot.');
			END IF;
			l_value := l_safe_object.get('results');
			IF l_value IS NULL OR NOT l_value.is_array() THEN
				raise_application_error(-20008, 'SharePoint response is missing results.');
			END IF;
			l_array := TREAT(l_value AS JSON_ARRAY_T);
			RETURN l_array;
		END collection_results;

		FUNCTION read_bindings(p_principal_id IN NUMBER) RETURN JSON_ARRAY_T IS
			l_assignments JSON_ARRAY_T;
			l_assignment JSON_OBJECT_T;
			l_roles JSON_OBJECT_T;
			l_roles_array JSON_ARRAY_T;
		BEGIN
			l_stage := 'read_bindings_request';
			l_assignment := read_object(l_item_url || '/roleassignments?$filter=PrincipalId%20eq%20' ||
				number_literal(p_principal_id) || '&$expand=RoleDefinitionBindings');
			l_stage := 'read_bindings_results';
			l_assignments := collection_results(l_assignment);
			IF l_assignments.get_size() = 0 THEN
				RETURN JSON_ARRAY_T();
			ELSIF l_assignments.get_size() <> 1 THEN
				raise_application_error(-20008, 'SharePoint returned multiple assignments for one principal.');
			END IF;
			l_stage := 'read_binding_assignment';
			l_assignment := TREAT(l_assignments.get(0) AS JSON_OBJECT_T);
			IF l_assignment IS NULL THEN
				raise_application_error(-20008, 'SharePoint returned a malformed assignment.');
			END IF;
			l_assignment.on_error(1);
			IF l_assignment.get_number('PrincipalId') <> p_principal_id
				OR l_assignment.get_number('PrincipalId') IS NULL THEN
				raise_application_error(-20008, 'SharePoint returned an unexpected permission principal.');
			END IF;
			l_stage := 'read_role_definition_bindings';
			l_roles := l_assignment.get_object('RoleDefinitionBindings');
			IF l_roles IS NULL THEN
				raise_application_error(-20008, 'SharePoint response is missing role bindings.');
			END IF;
			l_roles.on_error(1);
			l_stage := 'read_role_binding_results';
			l_roles_array := collection_results(l_roles);
			RETURN l_roles_array;
		END read_bindings;

		FUNCTION is_protected_role(p_role IN JSON_OBJECT_T) RETURN BOOLEAN IS
		BEGIN
			RETURN response_number(p_role, 'RoleTypeKind') = 1 OR response_boolean(p_role, 'Hidden');
		END is_protected_role;

		FUNCTION regular_role_bindings(p_roles IN JSON_ARRAY_T) RETURN JSON_ARRAY_T IS
			l_roles JSON_ARRAY_T := JSON_ARRAY_T();
			l_role JSON_OBJECT_T;
			l_role_id NUMBER;
		BEGIN
			IF p_roles.get_size() > 0 THEN
				FOR role_index IN 0 .. p_roles.get_size() - 1 LOOP
					l_role := TREAT(p_roles.get(role_index) AS JSON_OBJECT_T);
					IF l_role IS NULL THEN
						raise_application_error(-20008, 'SharePoint returned a malformed role binding.');
					END IF;
					l_role.on_error(1);
					l_role_id := required_response_id(l_role);
					IF NOT is_protected_role(l_role) THEN
						l_roles.append(l_role);
					END IF;
				END LOOP;
			END IF;
			RETURN l_roles;
		END regular_role_bindings;

		FUNCTION matches_role(p_roles IN JSON_ARRAY_T, p_role_id IN NUMBER) RETURN BOOLEAN IS
			l_regular_roles JSON_ARRAY_T := regular_role_bindings(p_roles);
			l_role JSON_OBJECT_T;
		BEGIN
			IF l_regular_roles.get_size() <> 1 THEN
				RETURN FALSE;
			END IF;
			l_role := TREAT(l_regular_roles.get(0) AS JSON_OBJECT_T);
			l_role.on_error(1);
			RETURN required_response_id(l_role) = p_role_id;
		END matches_role;

		FUNCTION contains_role(p_roles IN JSON_ARRAY_T, p_role_id IN NUMBER) RETURN BOOLEAN IS
			l_role JSON_OBJECT_T;
		BEGIN
			IF p_roles.get_size() > 0 THEN
				FOR role_index IN 0 .. p_roles.get_size() - 1 LOOP
					l_role := TREAT(p_roles.get(role_index) AS JSON_OBJECT_T);
					IF l_role IS NULL THEN
						raise_application_error(-20008, 'SharePoint returned a malformed role binding.');
					END IF;
					l_role.on_error(1);
					IF required_response_id(l_role) = p_role_id THEN
						RETURN TRUE;
					END IF;
				END LOOP;
			END IF;
			RETURN FALSE;
		END contains_role;

		PROCEDURE require_replaceable(p_roles IN JSON_ARRAY_T) IS
			l_role JSON_OBJECT_T;
		BEGIN
			IF p_roles.get_size() > 0 THEN
				FOR role_index IN 0 .. p_roles.get_size() - 1 LOOP
					l_role := TREAT(p_roles.get(role_index) AS JSON_OBJECT_T);
					IF l_role IS NULL THEN
						raise_application_error(-20008, 'SharePoint returned a malformed role binding.');
					END IF;
					l_role.on_error(1);
					IF is_protected_role(l_role) THEN
						raise_application_error(-20001, 'Cannot remove an assignment containing system-managed or hidden role bindings.');
					END IF;
				END LOOP;
			END IF;
		END require_replaceable;

		FUNCTION has_manage_permissions(p_mask IN JSON_OBJECT_T) RETURN BOOLEAN IS
			l_mask JSON_OBJECT_T;
			l_low_text VARCHAR2(4000);
			l_low NUMBER;
		BEGIN
			IF p_mask IS NULL THEN
				raise_application_error(-20008, 'SharePoint permission mask is missing.');
			END IF;
			l_mask := p_mask.clone();
			l_mask.on_error(1);
			l_low_text := l_mask.get_string('Low');
			IF l_low_text IS NULL OR NOT REGEXP_LIKE(l_low_text, '^[0-9]{1,10}$') THEN
				raise_application_error(-20008, 'SharePoint permission mask is missing or invalid.');
			END IF;
			l_low := TO_NUMBER(l_low_text);
			IF l_low > 4294967295 THEN
				raise_application_error(-20008, 'SharePoint permission mask is invalid.');
			END IF;
			RETURN BITAND(l_low, 33554432) <> 0;
		END has_manage_permissions;

		PROCEDURE require_manage_permissions IS
			l_permissions_object JSON_OBJECT_T;
			l_effective JSON_OBJECT_T;
		BEGIN
			l_permissions_object := read_object(l_item_url || '?$select=EffectiveBasePermissions');
			l_effective := l_permissions_object.get_object('EffectiveBasePermissions');
			IF l_effective IS NULL THEN
				raise_application_error(-20008, 'SharePoint response is missing EffectiveBasePermissions.');
			END IF;
			IF NOT has_manage_permissions(l_effective) THEN
				raise_application_error(-20001, 'The executing account requires ManagePermissions on the item.');
			END IF;
		END require_manage_permissions;

		FUNCTION progress_data RETURN JSON_OBJECT_T IS
			l_data JSON_OBJECT_T := JSON_OBJECT_T();
		BEGIN
			l_data.put('stage', l_stage);
			l_data.put('inheritance_broken', l_inheritance_broken);
			l_data.put('acl_changes_applied', l_partial_changes);
			l_data.put('partial_changes', l_partial_changes AND l_stage <> 'completed');
			l_data.put('write_outcome_uncertain', l_write_uncertain);
			l_data.put('site_user_registration_attempted', l_user_registration_attempted);
			l_data.put('completed_count', l_completed_count);
			l_data.put('results', l_results);
			IF l_last_mutation IS NOT NULL THEN
				l_data.put('last_completed_mutation', l_last_mutation);
			END IF;
			IF l_current_index IS NOT NULL THEN
				l_data.put('input_index', l_current_index);
				IF l_permissions.EXISTS(l_current_index) THEN
					l_data.put('principal_id', l_permissions(l_current_index).principal_id);
					l_data.put('role_id', l_permissions(l_current_index).role_id);
				END IF;
			END IF;
			IF l_original_roles IS NOT NULL THEN
				l_data.put('previous_role_bindings', l_original_roles);
			END IF;
			RETURN l_data;
		END progress_data;
	BEGIN
		l_raise_on_error := NVL(UPPER(TRIM(p_raise_on_error)), 'N');
		IF l_raise_on_error NOT IN ('Y', 'N') THEN
			raise_application_error(-20001, 'p_raise_on_error must be Y or N.');
		END IF;
		require_id(p_item_id, 'p_item_id');
		l_web_url := normalize_site_url(p_site_url) || '/_api/web';
		l_item_url := list_items_endpoint(p_site_url, p_list_title) || '(' || number_literal(p_item_id) || ')';
		BEGIN
			IF p_permissions_json IS NULL THEN
				raise_application_error(-20001, 'p_permissions_json is required.');
			END IF;
			l_input := JSON_ARRAY_T.parse(p_permissions_json);
		EXCEPTION
			WHEN OTHERS THEN
				raise_application_error(-20001, 'p_permissions_json must be a valid JSON array.');
		END;
		IF l_input.get_size() = 0 OR l_input.get_size() > 100 THEN
			raise_application_error(-20001, 'Provide between 1 and 100 permission entries per call.');
		END IF;
		FOR input_index IN 1 .. l_input.get_size() LOOP
			l_current_index := input_index;
			l_element := l_input.get(input_index - 1);
			IF NOT l_element.is_object() THEN
				raise_application_error(-20001, 'Each permission entry must be a JSON object.');
			END IF;
			l_entry := TREAT(l_element AS JSON_OBJECT_T);
			l_entry.on_error(0);
			l_keys := l_entry.get_keys();
			FOR key_index IN 1 .. l_keys.COUNT LOOP
				IF l_keys(key_index) NOT IN ('action', 'type', 'login_name', 'group_name', 'group_id', 'role_name', 'role_id') THEN
					raise_application_error(-20001, 'Unknown permission entry field: ' || SUBSTR(l_keys(key_index), 1, 100));
				END IF;
			END LOOP;
			l_permissions(input_index).operation := NVL(UPPER(input_text(l_entry, 'action')), 'REPLACE');
			IF l_permissions(input_index).operation NOT IN ('REPLACE', 'REMOVE_DIRECT') THEN
				raise_application_error(-20001, 'action must be REPLACE or REMOVE_DIRECT.');
			END IF;
			IF l_operation IS NULL THEN
				l_operation := l_permissions(input_index).operation;
			ELSIF l_operation <> l_permissions(input_index).operation THEN
				raise_application_error(-20001, 'All entries in one call must use the same action.');
			END IF;
			l_permissions(input_index).principal_type := UPPER(input_text(l_entry, 'type'));
			l_permissions(input_index).role_manages_permissions := FALSE;
			l_permissions(input_index).contains_executing_account := FALSE;
			l_permissions(input_index).unchanged_self_group := FALSE;
			l_permissions(input_index).duplicate_entry := FALSE;
			IF l_permissions(input_index).principal_type IN ('USER', 'DIRECTORY_GROUP') THEN
				IF NOT l_entry.has('login_name') OR l_entry.has('group_name') OR l_entry.has('group_id') THEN
					raise_application_error(-20001, l_permissions(input_index).principal_type ||
						' requires only login_name as its principal selector.');
				END IF;
				l_permissions(input_index).principal_name := input_text(l_entry, 'login_name');
			ELSIF l_permissions(input_index).principal_type = 'SHAREPOINT_GROUP' THEN
				IF l_entry.has('login_name') OR l_entry.has('group_name') = l_entry.has('group_id') THEN
					raise_application_error(-20001, 'SHAREPOINT_GROUP requires exactly one of group_name/group_id.');
				END IF;
				l_permissions(input_index).principal_name := input_text(l_entry, 'group_name');
				l_permissions(input_index).principal_id := input_id(l_entry, 'group_id');
			ELSE
				raise_application_error(-20001, 'type must be USER, DIRECTORY_GROUP, or SHAREPOINT_GROUP.');
			END IF;
			IF l_permissions(input_index).operation = 'REPLACE' THEN
				IF l_entry.has('role_name') = l_entry.has('role_id') THEN
					raise_application_error(-20001, 'REPLACE requires exactly one of role_name/role_id.');
				END IF;
				l_permissions(input_index).role_name := input_text(l_entry, 'role_name');
				l_permissions(input_index).role_id := input_id(l_entry, 'role_id');
			ELSE
				IF l_entry.has('role_name') OR l_entry.has('role_id') THEN
					raise_application_error(-20001, 'REMOVE_DIRECT does not accept role_name or role_id.');
				END IF;
			END IF;
		END LOOP;

		l_current_index := NULL;
		l_stage := 'read_item';
		l_item := read_object(l_item_url || '?$select=Id,HasUniqueRoleAssignments');
		IF required_response_id(l_item) <> p_item_id OR NOT l_item.has('HasUniqueRoleAssignments') THEN
			raise_application_error(-20008, 'SharePoint returned unexpected item metadata.');
		END IF;
		l_has_unique_assignments := response_boolean(l_item, 'HasUniqueRoleAssignments');
		IF l_operation = 'REMOVE_DIRECT' AND NOT l_has_unique_assignments THEN
			FOR permission_index IN 1 .. l_permissions.COUNT LOOP
				l_current_index := permission_index;
				l_report := JSON_OBJECT_T();
				l_report.put('input_index', permission_index);
				l_report.put('action', l_operation);
				l_report.put('principal_type', l_permissions(permission_index).principal_type);
				l_report.put('principal_id', l_permissions(permission_index).principal_id);
				l_report.put('status', 'unchanged');
				l_results.append(l_report);
				l_completed_count := l_completed_count + 1;
			END LOOP;
			l_current_index := NULL;
			l_stage := 'completed';
			l_progress := progress_data();
			l_data_clob := l_progress.to_clob();
			l_result := workflow_success('set_list_item_permissions', 'No direct item permissions to remove.',
				p_item_id => p_item_id, p_data_json => l_data_clob);
			free_temp_clob(l_data_clob);
			RETURN l_result;
		END IF;
		l_stage := 'check_executing_account';
		l_object := read_object(l_web_url || '/currentuser?$select=Id,IsSiteAdmin');
		l_current_user_id := required_response_id(l_object);
		IF NOT l_object.has('IsSiteAdmin') THEN
			raise_application_error(-20008, 'SharePoint currentuser metadata is incomplete.');
		END IF;
		l_is_site_admin := response_boolean(l_object, 'IsSiteAdmin');
		require_manage_permissions();

		FOR permission_index IN 1 .. l_permissions.COUNT LOOP
			l_current_index := permission_index;
			IF l_permissions(permission_index).operation = 'REPLACE' THEN
				l_stage := 'resolve_role';
				IF l_permissions(permission_index).role_id IS NOT NULL THEN
					l_object := read_object(l_web_url || '/roledefinitions/getbyid(' ||
						number_literal(l_permissions(permission_index).role_id) || ')');
				ELSE
					l_object := read_object(l_web_url || '/roledefinitions/getbyname(' ||
						odata_string_literal(l_permissions(permission_index).role_name) || ')');
				END IF;
				l_permissions(permission_index).role_id := required_response_id(l_object);
				IF response_boolean(l_object, 'Hidden') OR response_number(l_object, 'RoleTypeKind') = 1 THEN
					raise_application_error(-20001, 'Cannot assign a hidden role or Limited Access.');
				END IF;
				l_requested_role := l_object;
			END IF;
			l_stage := 'resolve_principal';
			IF l_permissions(permission_index).principal_type IN ('USER', 'DIRECTORY_GROUP') THEN
				ensure_digest();
				l_object := JSON_OBJECT_T();
				l_object.put('logonName', l_permissions(permission_index).principal_name);
				l_payload := l_object.to_clob();
				l_user_registration_attempted := TRUE;
				l_response := shp_post_ex(l_web_url || '/ensureuser', l_payload, l_digest);
				free_temp_clob(l_payload);
				l_object := response_data();
				IF l_permissions(permission_index).principal_type = 'USER'
					AND response_number(l_object, 'PrincipalType') <> 1 THEN
					raise_application_error(-20001, 'USER login must resolve to an individual user, not a directory group.');
				END IF;
				IF l_permissions(permission_index).principal_type = 'DIRECTORY_GROUP'
					AND response_number(l_object, 'PrincipalType') <> 4 THEN
					raise_application_error(-20001, 'DIRECTORY_GROUP login must resolve to an Active Directory security group.');
				END IF;
			ELSE
				IF l_permissions(permission_index).principal_id IS NOT NULL THEN
					l_object := read_object(l_web_url || '/sitegroups/getbyid(' ||
						number_literal(l_permissions(permission_index).principal_id) || ')');
				ELSE
					l_object := read_object(l_web_url || '/sitegroups/getbyname(' ||
						odata_string_literal(l_permissions(permission_index).principal_name) || ')');
				END IF;
			END IF;
			l_permissions(permission_index).principal_id := required_response_id(l_object);
			IF l_permissions(permission_index).principal_id = l_current_user_id THEN
				raise_application_error(-20001, 'Refusing to replace the executing account''s direct permissions.');
			END IF;
			IF l_permissions(permission_index).principal_type = 'SHAREPOINT_GROUP' AND NOT l_is_site_admin THEN
				l_object := read_object(l_web_url || '/sitegroups/getbyid(' ||
					number_literal(l_permissions(permission_index).principal_id) ||
					')/users?$select=Id,PrincipalType');
				l_bindings := collection_results(l_object);
				IF l_bindings.get_size() > 0 THEN
					FOR member_index IN 0 .. l_bindings.get_size() - 1 LOOP
						l_object := TREAT(l_bindings.get(member_index) AS JSON_OBJECT_T);
						IF l_object IS NULL THEN
							raise_application_error(-20008, 'SharePoint returned a malformed group member.');
						END IF;
						l_object.on_error(1);
						IF required_response_id(l_object) = l_current_user_id THEN
							l_permissions(permission_index).contains_executing_account := TRUE;
						END IF;
						IF response_number(l_object, 'PrincipalType') NOT IN (1, 4) THEN
							raise_application_error(-20001, 'SharePoint groups may contain only users and Active Directory security groups.');
						END IF;
					END LOOP;
				END IF;
			END IF;
			IF l_permissions(permission_index).contains_executing_account
				AND l_permissions(permission_index).operation = 'REMOVE_DIRECT' THEN
				raise_application_error(-20001, 'Refusing to remove permissions for a group containing the executing account.');
			END IF;
			IF l_permissions(permission_index).contains_executing_account
				AND l_permissions(permission_index).operation = 'REPLACE' THEN
				l_permissions(permission_index).role_manages_permissions :=
					has_manage_permissions(l_requested_role.get_object('BasePermissions'));
			END IF;
			IF permission_index > 1 THEN
				FOR previous_index IN 1 .. permission_index - 1 LOOP
					IF l_permissions(previous_index).principal_id = l_permissions(permission_index).principal_id THEN
						IF l_permissions(previous_index).role_id <> l_permissions(permission_index).role_id THEN
							raise_application_error(-20001, 'Conflicting roles requested for the same resolved principal.');
						END IF;
						l_permissions(permission_index).duplicate_entry := TRUE;
					END IF;
				END LOOP;
			END IF;
			l_stage := 'preflight_read_bindings';
			IF l_permissions(permission_index).operation = 'REPLACE' THEN
				l_bindings := read_bindings(l_permissions(permission_index).principal_id);
				l_stage := 'preflight_validate_existing_roles';
				IF l_permissions(permission_index).contains_executing_account THEN
					l_permissions(permission_index).unchanged_self_group :=
						matches_role(l_bindings, l_permissions(permission_index).role_id);
					IF NOT l_permissions(permission_index).unchanged_self_group
						AND NOT l_permissions(permission_index).role_manages_permissions THEN
						raise_application_error(-20001, 'Changing permissions for a group containing the executing account requires a role with ManagePermissions.');
					END IF;
				END IF;
				l_bindings := regular_role_bindings(l_bindings);
			END IF;
			IF NOT l_permissions(permission_index).unchanged_self_group THEN
				l_requires_unique_scope := TRUE;
			END IF;
		END LOOP;

		l_current_index := NULL;
		IF l_requires_unique_scope THEN
			l_stage := 'check_inheritance';
			l_item := read_object(l_item_url || '?$select=HasUniqueRoleAssignments');
			IF NOT l_item.has('HasUniqueRoleAssignments') THEN
				raise_application_error(-20008, 'SharePoint response is missing HasUniqueRoleAssignments.');
			END IF;
			l_has_unique_assignments := response_boolean(l_item, 'HasUniqueRoleAssignments');
			IF NOT l_has_unique_assignments THEN
				l_stage := 'break_inheritance';
				mutate(l_item_url || '/breakroleinheritance(copyRoleAssignments=true,clearSubscopes=false)');
				l_inheritance_broken := TRUE;
			END IF;
			l_stage := 'verify_unique_scope';
			l_item := read_object(l_item_url || '?$select=HasUniqueRoleAssignments');
			IF NOT response_boolean(l_item, 'HasUniqueRoleAssignments') THEN
				raise_application_error(-20008, 'Item permissions are still inherited.');
			END IF;
		END IF;
		require_manage_permissions();
		FOR permission_index IN 1 .. l_permissions.COUNT LOOP
			IF NOT l_permissions(permission_index).duplicate_entry THEN
				l_current_index := permission_index;
				l_stage := 'read_current_roles';
				l_bindings := read_bindings(l_permissions(permission_index).principal_id);
				l_original_roles := l_bindings;
				l_report := JSON_OBJECT_T();
				l_report.put('input_index', permission_index);
				l_report.put('action', l_permissions(permission_index).operation);
				l_report.put('principal_type', l_permissions(permission_index).principal_type);
				l_report.put('principal_id', l_permissions(permission_index).principal_id);
				IF l_permissions(permission_index).operation = 'REMOVE_DIRECT' THEN
					IF l_bindings.get_size() = 0 THEN
						l_report.put('status', 'unchanged');
					ELSE
						require_replaceable(l_bindings);
						l_stage := 'remove_assignment';
						mutate(l_item_url || '/roleassignments/getbyprincipalid(' ||
							number_literal(l_permissions(permission_index).principal_id) || ')', 'DELETE');
						l_stage := 'verify_removed_assignment';
						l_bindings := read_bindings(l_permissions(permission_index).principal_id);
						IF l_bindings.get_size() <> 0 THEN
							raise_application_error(-20008, 'SharePoint retained direct role bindings after REMOVE_DIRECT.');
						END IF;
						l_report.put('status', 'removed');
						require_manage_permissions();
					END IF;
				ELSE
					l_report.put('role_id', l_permissions(permission_index).role_id);
					IF matches_role(l_bindings, l_permissions(permission_index).role_id) THEN
						l_report.put('status', 'unchanged');
					ELSE
						IF l_permissions(permission_index).unchanged_self_group THEN
							raise_application_error(-20001, 'Permissions for a group containing the executing account changed after validation; retry from the current state.');
						END IF;
						IF NOT contains_role(l_bindings, l_permissions(permission_index).role_id) THEN
							l_stage := 'add_assignment';
							mutate(l_item_url || '/roleassignments/addroleassignment(principalid=' ||
								number_literal(l_permissions(permission_index).principal_id) || ',roledefid=' ||
								number_literal(l_permissions(permission_index).role_id) || ')');
							l_stage := 'verify_added_assignment';
							l_bindings := read_bindings(l_permissions(permission_index).principal_id);
							IF NOT contains_role(l_bindings, l_permissions(permission_index).role_id) THEN
								raise_application_error(-20008, 'SharePoint did not retain the requested role binding.');
							END IF;
						END IF;
						IF l_original_roles.get_size() > 0 THEN
							FOR role_index IN 0 .. l_original_roles.get_size() - 1 LOOP
								l_object := TREAT(l_original_roles.get(role_index) AS JSON_OBJECT_T);
								IF l_object IS NULL THEN
									raise_application_error(-20008, 'SharePoint returned a malformed previous role binding.');
								END IF;
								l_object.on_error(1);
								IF required_response_id(l_object) <> l_permissions(permission_index).role_id
									AND NOT is_protected_role(l_object) THEN
									l_stage := 'remove_role_binding';
									mutate(l_item_url || '/roleassignments/removeroleassignment(principalid=' ||
										number_literal(l_permissions(permission_index).principal_id) || ',roledefid=' ||
										number_literal(required_response_id(l_object)) || ')');
								END IF;
							END LOOP;
						END IF;
						l_stage := 'verify_assignment';
						l_bindings := read_bindings(l_permissions(permission_index).principal_id);
						IF NOT matches_role(l_bindings, l_permissions(permission_index).role_id) THEN
							raise_application_error(-20008, 'SharePoint regular role bindings do not match the requested role after cleanup.');
						END IF;
						l_report.put('status', 'updated');
						require_manage_permissions();
					END IF;
				END IF;
				l_results.append(l_report);
				l_completed_count := l_completed_count + 1;
				l_original_roles := NULL;
			END IF;
		END LOOP;
		l_current_index := NULL;
		l_stage := 'completed';
		l_progress := progress_data();
		l_data_clob := l_progress.to_clob();
		l_result := workflow_success('set_list_item_permissions',
			CASE WHEN l_operation = 'REMOVE_DIRECT' THEN 'Direct item permissions removed.'
				ELSE 'Direct item permissions set.' END,
			p_item_id => p_item_id, p_data_json => l_data_clob);
		free_temp_clob(l_data_clob);
		RETURN l_result;
	EXCEPTION
		WHEN OTHERS THEN
			l_error_code := SQLCODE;
			l_error_detail := SQLERRM;
			free_temp_clob(l_response);
			free_temp_clob(l_payload);
			free_temp_clob(l_data_clob);
			IF l_raise_on_error = 'Y' THEN
				BEGIN
					APEX_DEBUG.error('SHP_API.set_list_item_permissions stage=%s input_index=%s completed=%s partial=%s uncertain=%s code=%s',
						l_stage, TO_CHAR(l_current_index), TO_CHAR(l_completed_count),
						CASE WHEN l_partial_changes THEN 'Y' ELSE 'N' END,
						CASE WHEN l_write_uncertain THEN 'Y' ELSE 'N' END, TO_CHAR(l_error_code));
				EXCEPTION
					WHEN OTHERS THEN NULL;
				END;
				RAISE;
			END IF;
			l_result := workflow_error('set_list_item_permissions', l_error_code, l_error_detail);
			l_object := JSON_OBJECT_T.parse(l_result);
			free_temp_clob(l_result);
			l_progress := progress_data();
			l_object.put('item_id', p_item_id);
			l_object.put('data', l_progress);
			RETURN l_object.to_clob();
	END set_list_item_permissions;

END "SHP_API";
/
