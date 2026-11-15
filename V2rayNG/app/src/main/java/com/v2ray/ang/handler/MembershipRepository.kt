package com.v2ray.ang.handler

import com.v2ray.ang.BuildConfig
import com.v2ray.ang.util.LogUtil
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.coroutineContext
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

data class Membership(val status: String, val remainingDays: Int)
enum class MembershipError { UNAVAILABLE, INVALID_KEY, USED_KEY, EXPIRED_KEY, NETWORK, PROFILE_UNAVAILABLE, NOT_ACTIVE, STORAGE }
class MembershipException(val reason: MembershipError) : IOException(reason.name)

interface MembershipSource {
    val configured: Boolean
    suspend fun fetch(key: String? = null): Membership
    suspend fun prepareProfile(name: String): Membership
}

/** Owns the activation API, separate from subscriptions containing VPN profile lists. */
class MembershipRepository : MembershipSource {
    private val base = BuildConfig.JOKER_ACTIVATION_URL.trimEnd('/')
    override val configured = base.startsWith("https://")
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS).readTimeout(15, TimeUnit.SECONDS)
        .callTimeout(20, TimeUnit.SECONDS).followRedirects(false).followSslRedirects(false).build()

    override suspend fun fetch(key: String?): Membership = request(key, false, "")

    override suspend fun prepareProfile(name: String): Membership = request(null, true, name)

    private suspend fun request(key: String?, includeProfile: Boolean, profileName: String): Membership = withContext(Dispatchers.IO) {
        if (!configured) throw MembershipException(MembershipError.UNAVAILABLE)
        try {
            val token = MmkvManager.getOrCreateMembershipToken()
            val body = JSONObject().apply {
                if (key != null) put("key", key)
                if (includeProfile) put("include_profile", true)
            }.toString()
            val request = Request.Builder().url(base + if (key == null) "/v1/status" else "/v1/redeem")
                .header("Authorization", "Bearer $token")
                .post(body.toRequestBody("application/json".toMediaType())).build()
            val (successful, text) = awaitResponse(client.newCall(request))
            val parsed = withContext(Dispatchers.Default) {
                val result = JSONObject(text)
                if (!successful) {
                    throw MembershipException(when (result.optString("error")) {
                        "invalid_key" -> MembershipError.INVALID_KEY
                        "used_key" -> MembershipError.USED_KEY
                        "expired_key" -> MembershipError.EXPIRED_KEY
                        "profile_unavailable" -> MembershipError.PROFILE_UNAVAILABLE
                        else -> MembershipError.NETWORK
                    })
                }
                MembershipPayload.parse(text, includeProfile, profileName)
            }
            coroutineContext.ensureActive()
            parsed.profile?.let { MmkvManager.saveMembershipProfile(it) }
            parsed.membership
        } catch (error: CancellationException) {
            throw error
        } catch (error: ProfileStorageException) {
            LogUtil.e(message = "Membership profile save failed", throwable = IOException(error.javaClass.simpleName))
            throw MembershipException(MembershipError.STORAGE)
        } catch (error: MembershipException) {
            throw error
        } catch (error: Exception) {
            // Exceptions from HTTP may include endpoint details; log a sanitized failure.
            LogUtil.e(message = "Membership request failed", throwable = IOException(error.javaClass.simpleName))
            throw MembershipException(MembershipError.NETWORK)
        }
    }

    /** Own the HTTP call with the requesting ViewModel; cancellation closes the response. */
    internal suspend fun awaitResponse(call: Call): Pair<Boolean, String> = suspendCancellableCoroutine { continuation ->
        continuation.invokeOnCancellation { call.cancel() }
        call.enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                if (continuation.isActive) continuation.resumeWithException(e)
            }

            override fun onResponse(call: Call, response: Response) {
                try {
                    val result = response.use {
                        val bytes = it.peekBody(4097).bytes()
                        if (bytes.size > 4096) throw IOException("Invalid response length")
                        it.isSuccessful to bytes.toString(Charsets.UTF_8)
                    }
                    if (continuation.isActive) continuation.resume(result)
                } catch (error: Exception) {
                    if (continuation.isActive) continuation.resumeWithException(error)
                }
            }
        })
    }
}
