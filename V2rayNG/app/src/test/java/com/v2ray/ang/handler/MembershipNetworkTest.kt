package com.v2ray.ang.handler

import kotlinx.coroutines.*
import okhttp3.Call
import okhttp3.Callback
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import org.mockito.kotlin.*
import java.io.IOException

class MembershipNetworkTest {
    @Test fun cancellationCancelsTheCallAndLateFailureIsIgnored() = runBlocking {
        val call = mock<Call>()
        var callback: Callback? = null
        doAnswer { callback = it.getArgument(0); null }.whenever(call).enqueue(any())
        val job = launch(start = CoroutineStart.UNDISPATCHED) { MembershipRepository().awaitResponse(call) }
        job.cancelAndJoin()
        verify(call).cancel()
        callback!!.onFailure(call, IOException("late failure"))
        assertTrue(job.isCancelled)
    }

    @Test fun bodyIsBoundedAndClosedOnSuccessAndFailure() = runBlocking {
        for (size in listOf(16, 4097)) {
            val call = mock<Call>()
            var callback: Callback? = null
            doAnswer { callback = it.getArgument(0); null }.whenever(call).enqueue(any())
            val outcome = CompletableDeferred<Result<Pair<Boolean, String>>>()
            val job = launch(start = CoroutineStart.UNDISPATCHED) {
                outcome.complete(runCatching { MembershipRepository().awaitResponse(call) })
            }
            val body = spy("x".repeat(size).toResponseBody())
            val response = Response.Builder().request(Request.Builder().url("https://example.com").build())
                .protocol(Protocol.HTTP_1_1).code(200).message("OK").body(body).build()
            callback!!.onResponse(call, response)
            val result = outcome.await()
            if (size <= 4096) assertEquals(true to "x".repeat(size), result.getOrThrow())
            else assertTrue(result.exceptionOrNull() is IOException)
            verify(body).close()
            job.join()
        }
    }
}
