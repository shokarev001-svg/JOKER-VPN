package com.v2ray.ang.handler

import com.google.gson.JsonParser
import com.v2ray.ang.enums.EConfigType
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class MembershipProfileTest {
    private val payload = """{
        "status":"active","remaining_days":1,"server_time":1000,"expires_at":87400,
        "vpn":{"schema":1,"id":"38394759-4033-4abc-8fc0-148c67c839a0",
        "host":"8.8.8.8","port":443,"network":"tcp","security":"reality",
        "sni":"www.example.com","public_key":"AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
        "short_id":"0123456789abcdef","flow":"xtls-rprx-vision"}}
    """.trimIndent()

    @Test fun parsesOnlyTheMembersValidatedProfile() {
        val parsed = MembershipPayload.parse(payload, true, "JOKER")
        assertEquals(Membership("active", 1), parsed.membership)
        val profile = parsed.profile!!
        assertEquals(EConfigType.VLESS, profile.configType)
        assertEquals("38394759-4033-4abc-8fc0-148c67c839a0", profile.password)
        assertEquals("8.8.8.8", profile.server)
        assertEquals("443", profile.serverPort)
        assertEquals("reality", profile.security)
        assertEquals("xtls-rprx-vision", profile.flow)
        assertEquals("chrome", profile.fingerPrint)
        assertEquals(false, profile.insecure)
        assertEquals("none", profile.method)
        assertEquals("JOKER", profile.remarks)
    }

    @Test fun legacyResponseAndMissingProfileAreHandledWithoutImport() {
        val body = JsonParser.parseString(payload).asJsonObject
        body.remove("vpn")
        assertNull(MembershipPayload.parse(body.toString(), false, "").profile)
        assertEquals(MembershipError.PROFILE_UNAVAILABLE,
            assertThrows(MembershipException::class.java) { MembershipPayload.parse(body.toString(), true, "JOKER") }.reason)
        body.addProperty("status", "expired")
        body.addProperty("remaining_days", 0)
        body.addProperty("expires_at", 1000)
        assertEquals(MembershipError.NOT_ACTIVE,
            assertThrows(MembershipException::class.java) { MembershipPayload.parse(body.toString(), true, "JOKER") }.reason)
    }

    @Test fun malformedOrInconsistentCredentialsAreRejected() {
        for ((field, value) in listOf("id" to "bad", "host" to "https://bad.example", "host" to "999.1.1.1",
            "network" to "ws", "security" to "none", "sni" to "bad/name", "public_key" to "bad",
            "short_id" to "1", "flow" to "unknown", "port" to "443", "schema" to "1")) {
            val body = JsonParser.parseString(payload).asJsonObject
            body.getAsJsonObject("vpn").addProperty(field, value)
            assertThrows(IllegalArgumentException::class.java) { MembershipPayload.parse(body.toString(), true, "JOKER") }
        }
        val body = JsonParser.parseString(payload).asJsonObject
        body.addProperty("remaining_days", 2)
        assertThrows(IllegalArgumentException::class.java) { MembershipPayload.parse(body.toString(), true, "JOKER") }
        assertThrows(IllegalArgumentException::class.java) { MembershipPayload.parse(payload, true, "") }
    }

    @Test fun failedPublicationRestoresOriginalProfileAndIndex() {
        for (failAt in listOf("payload", "index")) {
            var payload = "old profile"
            var index = "old list"
            assertThrows(IllegalStateException::class.java) {
                commitMembershipProfile(
                    savePayload = { payload = "new profile"; check(failAt != "payload") },
                    saveIndex = { index = "new list"; check(failAt != "index") },
                    restorePayload = { payload = "old profile" },
                    restoreIndex = { index = "old list" },
                )
            }
            assertEquals("old profile", payload)
            assertEquals("old list", index)
        }
    }

    @Test fun successfulPublicationAndFailedRollbackAreDistinguishable() {
        var payload = "old"
        var index = "old"
        commitMembershipProfile({ payload = "new" }, { index = "new" }, { payload = "old" }, { index = "old" })
        assertEquals("new", payload)
        assertEquals("new", index)
        var restoredIndex = false
        assertThrows(ProfileStorageException::class.java) {
            commitMembershipProfile({}, { error("write") }, { error("restore") }, { restoredIndex = true })
        }
        assertTrue(restoredIndex)
    }
}
