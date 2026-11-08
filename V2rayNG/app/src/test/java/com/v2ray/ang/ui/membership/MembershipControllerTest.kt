package com.v2ray.ang.ui.membership

import com.v2ray.ang.handler.*
import kotlinx.coroutines.*
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class MembershipControllerTest {
    private class Source(override val configured: Boolean = true) : MembershipSource {
        var calls = 0
        var receivedKey: String? = null
        var result = Membership("inactive", 0)
        var failure: MembershipError? = null
        var gate: CompletableDeferred<Unit>? = null
        override suspend fun fetch(key: String?): Membership {
            calls++
            receivedKey = key
            gate?.await()
            failure?.let { throw MembershipException(it) }
            return result
        }
    }

    @Test fun initialAndUnavailable() {
        val source = Source(false)
        val scope = CoroutineScope(Job() + Dispatchers.Unconfined)
        try {
            val controller = MembershipController(source, scope)
            assertEquals(MembershipUiState(false), controller.state.value)
            controller.onAction(MembershipAction.Refresh)
            assertEquals(MembershipError.UNAVAILABLE, controller.state.value.error)
            assertEquals(0, source.calls)
        } finally { scope.cancel() }
    }

    @Test fun emptyAndInvalidNeverReachServer() {
        val source = Source()
        val scope = CoroutineScope(Job() + Dispatchers.Unconfined)
        try {
            val controller = MembershipController(source, scope)
            for (key in listOf("", " ", "JOKER-123", "x".repeat(100))) {
                controller.onAction(MembershipAction.Redeem(key))
                assertEquals(MembershipError.INVALID_KEY, controller.state.value.error)
            }
            assertEquals(0, source.calls)
        } finally { scope.cancel() }
    }

    @Test fun refreshPresentsAllServerStates() {
        val source = Source()
        val scope = CoroutineScope(Job() + Dispatchers.Unconfined)
        try {
            val controller = MembershipController(source, scope)
            for (result in listOf(Membership("inactive", 0), Membership("active", 30), Membership("expired", 0))) {
                source.result = result
                controller.onAction(MembershipAction.Refresh)
                assertEquals(result, controller.state.value.membership)
                assertNull(controller.state.value.error)
                assertFalse(controller.state.value.loading)
            }
        } finally { scope.cancel() }
    }

    @Test fun normalizedKeyAndAllErrors() {
        val source = Source()
        val scope = CoroutineScope(Job() + Dispatchers.Unconfined)
        try {
            val controller = MembershipController(source, scope)
            controller.onAction(MembershipAction.Redeem(" joker-" + "a".repeat(48) + " "))
            assertEquals("JOKER-" + "A".repeat(48), source.receivedKey)
            for (error in MembershipError.entries) {
                source.failure = error
                controller.onAction(MembershipAction.Refresh)
                assertEquals(error, controller.state.value.error)
                assertNull(controller.state.value.membership)
                assertFalse(controller.state.value.loading)
            }
        } finally { scope.cancel() }
    }

    @Test fun loadingRejectsDuplicateSubmissionsAndScopeCancellationStopsWork() {
        val source = Source().apply { gate = CompletableDeferred() }
        val scope = CoroutineScope(Job() + Dispatchers.Unconfined)
        val controller = MembershipController(source, scope)
        controller.onAction(MembershipAction.Refresh)
        assertTrue(controller.state.value.loading)
        controller.onAction(MembershipAction.Redeem("JOKER-" + "A".repeat(48)))
        assertEquals(1, source.calls)
        scope.cancel()
        source.gate!!.complete(Unit)
        assertNull(controller.state.value.membership)
    }
}
