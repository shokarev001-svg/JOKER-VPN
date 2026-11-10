package com.v2ray.ang.ui.membership

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.v2ray.ang.handler.Membership
import com.v2ray.ang.handler.MembershipError
import com.v2ray.ang.handler.MembershipException
import com.v2ray.ang.handler.MembershipRepository
import com.v2ray.ang.handler.MembershipSource
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.util.Locale

data class MembershipUiState(
    val configured: Boolean,
    val loading: Boolean = false,
    val membership: Membership? = null,
    val error: MembershipError? = null,
)

sealed interface MembershipAction {
    data object Refresh : MembershipAction
    data class Redeem(val key: String) : MembershipAction
}

/** Independently testable owner of loading, validation and server results. */
class MembershipController(private val source: MembershipSource, private val scope: CoroutineScope) {
    private val mutableState = MutableStateFlow(MembershipUiState(configured = source.configured))
    val state = mutableState.asStateFlow()

    fun onAction(action: MembershipAction) {
        if (state.value.loading) return
        if (!source.configured) {
            mutableState.value = MembershipUiState(false, error = MembershipError.UNAVAILABLE)
            return
        }
        val key = (action as? MembershipAction.Redeem)?.key?.trim()?.uppercase(Locale.ROOT)
        if (key != null && !Regex("JOKER-[A-F0-9]{48}").matches(key)) {
            mutableState.value = state.value.copy(error = MembershipError.INVALID_KEY)
            return
        }
        // Do not present cached remaining days as a fresh server-verified entitlement.
        mutableState.value = MembershipUiState(true, loading = true)
        scope.launch {
            try {
                mutableState.value = MembershipUiState(true, membership = source.fetch(key))
            } catch (error: CancellationException) {
                throw error
            } catch (error: MembershipException) {
                mutableState.value = MembershipUiState(true, error = error.reason)
            }
        }
    }
}

class MembershipViewModel : ViewModel() {
    private val controller = MembershipController(MembershipRepository(), viewModelScope)
    val state = controller.state
    fun onAction(action: MembershipAction) = controller.onAction(action)
}
