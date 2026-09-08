from __future__ import annotations

from datetime import datetime, timezone

from app.integrations.selora.client import (
    SeloraApiClient,
    SeloraApiResponseError,
    SeloraWorkspaceState,
)
from app.models.import_workspace import (
    ImportWorkspace,
    LocalSyncStatus,
    RemoteWorkflowStatus,
)
from app.repositories.import_workspace_repository import (
    ImportWorkspaceRepository,
)


class RemoteWorkspaceStateError(RuntimeError):
    pass


class RemoteWorkspaceCoordinator:
    def __init__(
        self,
        *,
        client: SeloraApiClient,
        repository: ImportWorkspaceRepository,
        client_instance_id: str,
    ) -> None:
        self._client = client
        self._repository = repository
        self._client_instance_id = (
            client_instance_id
        )

    def resolve_and_acquire(
        self,
        *,
        workspace: ImportWorkspace,
        instagram_username: str,
    ) -> SeloraWorkspaceState:
        state = self._client.resolve_workspace(
            instagram_username=instagram_username,
            client_workspace_id=workspace.id,
            client_instance_id=self._client_instance_id,
            request_id=workspace.id,
        )

        self._apply_state(
            workspace=workspace,
            state=state,
        )

        if not state.is_editable:
            self._repository.commit()
            return state

        try:
            locked_state = (
                self._client
                .acquire_workspace_lock(
                    workspace_id=state.workspace_id,
                    client_workspace_id=workspace.id,
                    client_instance_id=(
                        self._client_instance_id
                    ),
                    expected_revision=(
                        state.revision
                    ),
                    request_id=workspace.id,
                )
            )
        except SeloraApiResponseError as exc:
            if exc.status_code == 423:
                workspace.remote_is_editable = False
                workspace.remote_lock_token = None
                workspace.remote_lock_expires_at = None
                workspace.remote_status_updated_at = (
                    datetime.now(
                        timezone.utc
                    )
                )
                self._repository.commit()

            raise

        self._apply_state(
            workspace=workspace,
            state=locked_state,
        )
        self._repository.commit()
        return locked_state

    def refresh(
        self,
        *,
        workspace: ImportWorkspace,
    ) -> SeloraWorkspaceState:
        workspace_id = (
            workspace.remote_workspace_id
        )

        if not workspace_id:
            raise RemoteWorkspaceStateError(
                "Remote workspace has not been resolved yet."
            )

        state = self._client.get_workspace(
            workspace_id=workspace_id,
            client_instance_id=(
                self._client_instance_id
            ),
            request_id=workspace.id,
        )

        self._apply_state(
            workspace=workspace,
            state=state,
        )
        self._repository.commit()
        return state

    def ensure_mutation_allowed(
        self,
        *,
        workspace: ImportWorkspace,
    ) -> None:
        if not workspace.remote_workspace_id:
            return

        state = self.refresh(
            workspace=workspace
        )

        if not state.is_editable:
            raise RemoteWorkspaceStateError(
                (
                    "این فضای واردسازی در سلورا "
                    "نهایی شده و فقط قابل مشاهده است."
                )
            )

        if (
            not workspace.remote_lock_token
            or not workspace.has_active_remote_lease
        ):
            raise RemoteWorkspaceStateError(
                (
                    "قفل ویرایش این Workspace در "
                    "اختیار این اپراتور نیست."
                )
            )

    def heartbeat(
        self,
        *,
        workspace: ImportWorkspace,
    ) -> SeloraWorkspaceState:
        if (
            not workspace.remote_workspace_id
            or not workspace.remote_lock_token
        ):
            raise RemoteWorkspaceStateError(
                "No active remote lease exists."
            )

        state = (
            self._client
            .renew_workspace_lock(
                workspace_id=(
                    workspace.remote_workspace_id
                ),
                client_workspace_id=workspace.id,
                client_instance_id=(
                    self._client_instance_id
                ),
                lock_token=(
                    workspace.remote_lock_token
                ),
                request_id=workspace.id,
            )
        )

        self._apply_state(
            workspace=workspace,
            state=state,
        )
        self._repository.commit()
        return state

    def release(
        self,
        *,
        workspace: ImportWorkspace,
    ) -> None:
        if (
            not workspace.remote_workspace_id
            or not workspace.remote_lock_token
        ):
            return

        try:
            state = (
                self._client
                .release_workspace_lock(
                    workspace_id=(
                        workspace.remote_workspace_id
                    ),
                    client_workspace_id=workspace.id,
                    client_instance_id=(
                        self._client_instance_id
                    ),
                    lock_token=(
                        workspace.remote_lock_token
                    ),
                    request_id=workspace.id,
                )
            )

            workspace.remote_revision = (
                state.revision
            )
        finally:
            workspace.remote_lock_token = None
            workspace.remote_lock_expires_at = None
            workspace.remote_status_updated_at = (
                datetime.now(
                    timezone.utc
                )
            )
            self._repository.commit()

    def apply_import_result(
        self,
        *,
        workspace: ImportWorkspace,
        state: SeloraWorkspaceState,
    ) -> None:
        self._apply_state(
            workspace=workspace,
            state=state,
        )
        workspace.local_sync_status = (
            LocalSyncStatus.SYNCED.value
        )
        workspace.last_synced_at = (
            datetime.now(
                timezone.utc
            )
        )
        workspace.last_sync_error = None
        self._repository.commit()

    @staticmethod
    def _apply_state(
        *,
        workspace: ImportWorkspace,
        state: SeloraWorkspaceState,
    ) -> None:
        workspace.remote_workspace_id = (
            state.workspace_id
        )
        workspace.remote_revision = (
            state.revision
        )
        workspace.remote_workflow_status = (
            state.workflow_status
        )
        workspace.remote_is_editable = (
            state.is_editable
        )
        workspace.remote_lock_token = (
            state.lock_token
        )
        workspace.remote_lock_expires_at = (
            state.lock_expires_at
        )
        workspace.remote_status_updated_at = (
            datetime.now(
                timezone.utc
            )
        )
