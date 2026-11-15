package com.v2ray.ang.handler

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.enums.EConfigType
import java.util.UUID

/** The small, versioned membership API format is never passed to the general importer. */
internal object MembershipPayload {
    data class Result(val membership: Membership, val profile: ProfileItem?)

    fun parse(text: String, requireProfile: Boolean, profileName: String): Result {
        val body = JsonParser.parseString(text).asJsonObject
        val status = body.string("status")
        val days = body.number("remaining_days")
        val now = body.number("server_time")
        val expires = body.number("expires_at")
        require(status in setOf("active", "inactive", "expired") && days in 0..Int.MAX_VALUE.toLong())
        require(now >= 0 && expires >= 0 && (status == "active") == (expires > now))
        require(days == if (expires > now) (expires - now - 1) / 86400 + 1 else 0)
        val membership = Membership(status, days.toInt())
        if (!requireProfile) return Result(membership, null)
        if (status != "active") throw MembershipException(MembershipError.NOT_ACTIVE)
        val vpn = body.get("vpn")?.takeUnless { it.isJsonNull }?.asJsonObject
            ?: throw MembershipException(MembershipError.PROFILE_UNAVAILABLE)
        require(vpn.number("schema") == 1L)
        val identity = vpn.string("id")
        val uuid = UUID.fromString(identity)
        require(uuid.version() == 4 && uuid.toString() == identity)
        val host = vpn.string("host")
        val parts = host.split('.')
        require(parts.size == 4 && parts.all { it.matches(Regex("0|[1-9][0-9]{0,2}")) && it.toInt() in 0..255 })
        val port = vpn.number("port")
        require(port in 1..65535)
        require(vpn.string("network") == "tcp" && vpn.string("security") == "reality")
        val sni = vpn.string("sni")
        require(sni.length <= 253 && sni.split('.').all {
            it.matches(Regex("[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"))
        })
        val publicKey = vpn.string("public_key")
        // Canonical unpadded base64url for 32 bytes; usable on the minimum Android API.
        require(publicKey.matches(Regex("[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]")))
        val shortId = vpn.string("short_id")
        require(shortId.matches(Regex("(?:[0-9a-f]{2}){0,8}")))
        val flow = vpn.string("flow")
        require(flow in setOf("", "xtls-rprx-vision"))
        require(profileName.isNotBlank() && profileName.length <= 100)
        return Result(membership, ProfileItem(
            configType = EConfigType.VLESS, remarks = profileName,
            server = host, serverPort = port.toString(), password = identity, method = "none",
            network = "tcp", security = "reality", sni = sni, fingerPrint = "chrome",
            publicKey = publicKey, shortId = shortId, flow = flow, insecure = false,
        ))
    }

    private fun JsonObject.string(key: String): String {
        val item = get(key)?.takeIf { it.isJsonPrimitive }?.asJsonPrimitive
        require(item != null && item.isString)
        return item.asString
    }

    private fun JsonObject.number(key: String): Long {
        val item = get(key)?.takeIf { it.isJsonPrimitive }?.asJsonPrimitive
        require(item != null && item.isNumber && item.asString.matches(Regex("0|[1-9][0-9]*")))
        return item.asString.toLong()
    }
}

/** Called under MMKV's profile lock; restores both records on a failed publication. */
internal fun commitMembershipProfile(
    savePayload: () -> Unit,
    saveIndex: () -> Unit,
    restorePayload: () -> Unit,
    restoreIndex: () -> Unit,
) {
    try {
        savePayload()
        saveIndex()
    } catch (failure: Exception) {
        val payloadRestored = runCatching(restorePayload).isSuccess
        val indexRestored = runCatching(restoreIndex).isSuccess
        if (!payloadRestored || !indexRestored) throw ProfileStorageException("Membership profile rollback failed")
        throw failure
    }
}
