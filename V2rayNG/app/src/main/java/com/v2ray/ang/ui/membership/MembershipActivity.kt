package com.v2ray.ang.ui.membership

import androidx.activity.viewModels
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.v2ray.ang.R
import com.v2ray.ang.handler.MembershipError
import com.v2ray.ang.ui.base.BaseComponentActivity

class MembershipActivity : BaseComponentActivity() {
    private val model: MembershipViewModel by viewModels()

    @Composable
    override fun ScreenContent() {
        val state by model.state.collectAsStateWithLifecycle()
        val owner = LocalLifecycleOwner.current
        DisposableEffect(owner) {
            val observer = LifecycleEventObserver { _, event ->
                if (event == Lifecycle.Event.ON_RESUME) model.onAction(MembershipAction.Refresh)
            }
            owner.lifecycle.addObserver(observer)
            onDispose { owner.lifecycle.removeObserver(observer) }
        }
        MembershipScreen(state, model::onAction, ::finish)
    }
}

@Composable
private fun MembershipScreen(state: MembershipUiState, onAction: (MembershipAction) -> Unit, onBack: () -> Unit) {
    // A voucher is transient secret input, deliberately not written to saved-instance state.
    var key by remember { mutableStateOf("") }
    Scaffold { padding ->
        Column(Modifier.fillMaxSize().padding(padding).consumeWindowInsets(padding)
            .imePadding().verticalScroll(rememberScrollState()).padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)) {
            TextButton(onClick = onBack) { Text(stringResource(R.string.acc_back)) }
            Text(stringResource(R.string.joker_membership_title), style = MaterialTheme.typography.headlineMedium)
            if (state.loading) {
                CircularProgressIndicator()
                Text(stringResource(R.string.joker_membership_loading))
            }
            state.membership?.let { membership ->
                Text(stringResource(when (membership.status) {
                    "active" -> R.string.joker_membership_active
                    "expired" -> R.string.joker_membership_expired
                    else -> R.string.joker_membership_inactive
                }), style = MaterialTheme.typography.titleLarge)
                if (membership.status == "active") {
                    Text(stringResource(R.string.joker_membership_days, membership.remainingDays))
                }
            }
            state.error?.let { error ->
                Text(stringResource(when (error) {
                    MembershipError.UNAVAILABLE -> R.string.joker_membership_unavailable
                    MembershipError.INVALID_KEY -> R.string.joker_membership_invalid
                    MembershipError.USED_KEY -> R.string.joker_membership_used
                    MembershipError.EXPIRED_KEY -> R.string.joker_membership_key_expired
                    MembershipError.NETWORK -> R.string.joker_membership_network
                }), color = MaterialTheme.colorScheme.error)
            }
            OutlinedTextField(value = key, onValueChange = { if (it.length <= 128) key = it },
                label = { Text(stringResource(R.string.joker_membership_key)) },
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters),
                enabled = state.configured && !state.loading, singleLine = true, modifier = Modifier.fillMaxWidth())
            Button(onClick = { onAction(MembershipAction.Redeem(key)) },
                enabled = state.configured && !state.loading, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.joker_membership_redeem))
            }
            OutlinedButton(onClick = { onAction(MembershipAction.Refresh) },
                enabled = state.configured && !state.loading, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.joker_membership_refresh))
            }
            Text(stringResource(R.string.joker_membership_hint), style = MaterialTheme.typography.bodySmall)
        }
    }
}
