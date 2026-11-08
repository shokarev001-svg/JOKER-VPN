package com.v2ray.ang.handler

import com.v2ray.ang.BuildConfig
import com.v2ray.ang.util.LogUtil
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

data class Membership(val status: String, val remainingDays: Int)
enum class MembershipError { UNAVAILABLE, INVALID_KEY, USED_KEY, EXPIRED_KEY, NETWORK }
class MembershipException(val reason: MembershipError) : IOException(reason.name)

interface MembershipSource {
    val configured: Boolean
    suspend fun fetch(key: String? = null): Membership
}

/** Owns the activation API, separate from subscriptions containing VPN profile lists. */
class MembershipRepository : MembershipSource {
    private val base = BuildConfig.JOKER_ACTIVATION_URL.trimEnd('/')
    override val configured = base.startsWith("https://")
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS).readTimeout(15, TimeUnit.SECONDS)
        .callTimeout(20, TimeUnit.SECONDS).followRedirects(false).followSslRedirects(false).build()

    override suspend fun fetch(key: String?): Membership = withContext(Dispatchers.IO) {
        if (!configured) throw MembershipException(MembershipError.UNAVAILABLE)
        try {
            val token = MmkvManager.getOrCreateMembershipToken()
            val body = JSONObject().apply { if (key != null) put("key", key) }.toString()
            val request = Request.Builder().url(base + if (key == null) "/v1/status" else "/v1/redeem")
                .header("Authorization", "Bearer $token")
                .post(body.toRequestBody("application/json".toMediaType())).build()
            client.newCall(request).execute().use { response ->
                val text = response.peekBody(4097).string()
                if (text.length > 4096) throw IOException("Invalid response length")
                val result = JSONObject(text)
                if (!response.isSuccessful) {
                    throw MembershipException(when (result.optString("error")) {
                        "invalid_key" -> MembershipError.INVALID_KEY
                        "used_key" -> MembershipError.USED_KEY
                        "expired_key" -> MembershipError.EXPIRED_KEY
                        else -> MembershipError.NETWORK
                    })
                }
                val status = result.getString("status")
                val days = result.getInt("remaining_days")
                require(status in setOf("active", "expired", "inactive") && days >= 0)
                require((status == "active") == (days > 0))
                Membership(status, days)
            }
        } catch (error: MembershipException) {
            throw error
        } catch (error: Exception) {
            // Exceptions from HTTP may include endpoint details; log a sanitized failure.
            LogUtil.e(message = "Membership request failed", throwable = IOException(error.javaClass.simpleName))
            throw MembershipException(MembershipError.NETWORK)
        }
    }
}
