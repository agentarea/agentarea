"""Workspace-scoped repository base class."""

from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.context import UserContext
from ..logging.audit_logger import get_audit_logger
from .models import WorkspaceScopedMixin

T = TypeVar("T", bound=WorkspaceScopedMixin)


class WorkspaceScopedRepository[T: WorkspaceScopedMixin]:
    """Base repository class that provides workspace-scoped CRUD operations.

    This repository focuses on workspace-level data isolation rather than user-level.
    All operations are scoped to the current workspace, with created_by used for audit purposes.
    """

    def __init__(self, session: AsyncSession, model_class: type[T], user_context: UserContext):
        """Initialize repository with session, model class, and user context.

        Args:
            session: SQLAlchemy async session
            model_class: The model class this repository manages
            user_context: Current user and workspace context
        """
        self.session = session
        self.model_class = model_class
        self.user_context = user_context
        self.audit_logger = get_audit_logger()
        self.resource_type = model_class.__name__.lower().replace("orm", "").replace("model", "")

    def _get_workspace_filter(self):
        """Get the workspace filter for queries."""
        return self.model_class.workspace_id == self.user_context.workspace_id

    def _get_creator_workspace_filter(self):
        """Get the creator and workspace filter for queries."""
        return and_(
            self.model_class.created_by == self.user_context.user_id,
            self.model_class.workspace_id == self.user_context.workspace_id,
        )

    async def get_by_id(self, id: UUID | str, creator_scoped: bool = False) -> T | None:
        """Get a record by ID within the current workspace.

        Args:
            id: The record ID
            creator_scoped: If True, also filter by created_by (for user's own resources)

        Returns:
            The record if found, None otherwise
        """
        try:
            query = select(self.model_class).where(self.model_class.id == id)

            if creator_scoped:
                query = query.where(self._get_creator_workspace_filter())
            else:
                query = query.where(self._get_workspace_filter())

            result = await self.session.execute(query)
            record = result.scalar_one_or_none()

            # Log read access
            self.audit_logger.log_read(
                resource_type=self.resource_type,
                user_context=self.user_context,
                resource_id=id,
                creator_scoped=creator_scoped,
                found=record is not None,
            )

            return record
        except Exception as e:
            self.audit_logger.log_error(
                resource_type=self.resource_type,
                user_context=self.user_context,
                error=str(e),
                resource_id=id,
                operation="get_by_id",
            )
            raise

    async def get_by_id_or_raise(self, id: UUID | str, creator_scoped: bool = False) -> T:
        """Get a record by ID or raise NoResultFound.

        Args:
            id: The record ID
            creator_scoped: If True, also filter by created_by

        Returns:
            The record

        Raises:
            NoResultFound: If record not found in workspace
        """
        record = await self.get_by_id(id, creator_scoped)
        if record is None:
            raise NoResultFound(f"{self.model_class.__name__} with id {id} not found in workspace")
        return record

    async def list_all(
        self,
        creator_scoped: bool = False,
        limit: int | None = None,
        offset: int | None = None,
        **filters: Any,
    ) -> list[T]:
        """List all records in the current workspace.

        By default, returns ALL workspace resources (not just user's).
        Use creator_scoped=True to filter to only resources created by current user.

        Args:
            creator_scoped: If True, only return records created by current user
            limit: Maximum number of records to return
            offset: Number of records to skip
            **filters: Additional field filters

        Returns:
            List of records
        """
        try:
            query = select(self.model_class)

            # Apply workspace/creator filtering
            if creator_scoped:
                query = query.where(self._get_creator_workspace_filter())
            else:
                # Default behavior: return all workspace resources
                query = query.where(self._get_workspace_filter())

            # Apply additional filters
            for field, value in filters.items():
                if hasattr(self.model_class, field):
                    query = query.where(getattr(self.model_class, field) == value)

            # Apply pagination
            if offset is not None:
                query = query.offset(offset)
            if limit is not None:
                query = query.limit(limit)

            result = await self.session.execute(query)
            records = list(result.scalars().all())

            # Log list access
            self.audit_logger.log_list(
                resource_type=self.resource_type,
                user_context=self.user_context,
                count=len(records),
                filters=filters,
                creator_scoped=creator_scoped,
                limit=limit,
                offset=offset,
            )

            return records
        except Exception as e:
            self.audit_logger.log_error(
                resource_type=self.resource_type,
                user_context=self.user_context,
                error=str(e),
                operation="list_all",
                filters=filters,
            )
            raise

    async def count(self, creator_scoped: bool = False, **filters: Any) -> int:
        """Count records in the current workspace.

        Args:
            creator_scoped: If True, only count records created by current user
            **filters: Additional field filters

        Returns:
            Number of records
        """
        query = select(func.count(self.model_class.id))

        # Apply workspace/creator filtering
        if creator_scoped:
            query = query.where(self._get_creator_workspace_filter())
        else:
            query = query.where(self._get_workspace_filter())

        # Apply additional filters
        for field, value in filters.items():
            if hasattr(self.model_class, field):
                query = query.where(getattr(self.model_class, field) == value)

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def create(self, **kwargs: Any) -> T:
        """Create a new record in the current workspace.

        Automatically sets created_by and workspace_id from user context.

        Args:
            **kwargs: Field values for the new record

        Returns:
            The created record
        """
        try:
            # Automatically set created_by and workspace_id
            kwargs["created_by"] = self.user_context.user_id
            kwargs["workspace_id"] = self.user_context.workspace_id

            record = self.model_class(**kwargs)

            self.session.add(record)
            await self.session.commit()
            await self.session.refresh(record)

            # Log creation
            self.audit_logger.log_create(
                resource_type=self.resource_type,
                user_context=self.user_context,
                resource_id=record.id,
                resource_data=kwargs,
            )

            return record
        except Exception as e:
            await self.session.rollback()
            self.audit_logger.log_error(
                resource_type=self.resource_type,
                user_context=self.user_context,
                error=str(e),
                operation="create",
                resource_data=kwargs,
            )
            raise

    async def update(self, id: UUID | str, creator_scoped: bool = False, **kwargs: Any) -> T | None:
        """Update a record by ID within the current workspace.

        Args:
            id: The record ID
            creator_scoped: If True, only update records created by current user
            **kwargs: Field values to update

        Returns:
            The updated record if found, None otherwise
        """
        try:
            # Get record without logging (get_by_id already logs)
            query = select(self.model_class).where(self.model_class.id == id)

            if creator_scoped:
                query = query.where(self._get_creator_workspace_filter())
            else:
                query = query.where(self._get_workspace_filter())

            result = await self.session.execute(query)
            record = result.scalar_one_or_none()

            if record is None:
                return None

            # Store original data for audit
            original_data = {
                field: getattr(record, field) for field in kwargs.keys() if hasattr(record, field)
            }

            # Remove immutable fields from updates
            kwargs.pop("created_by", None)
            kwargs.pop("workspace_id", None)

            # Update fields
            for field, value in kwargs.items():
                if hasattr(record, field):
                    setattr(record, field, value)

            await self.session.commit()
            await self.session.refresh(record)

            # Log update
            self.audit_logger.log_update(
                resource_type=self.resource_type,
                user_context=self.user_context,
                resource_id=id,
                resource_data=kwargs,
                original_data=original_data,
                creator_scoped=creator_scoped,
            )

            return record
        except Exception as e:
            await self.session.rollback()
            self.audit_logger.log_error(
                resource_type=self.resource_type,
                user_context=self.user_context,
                error=str(e),
                resource_id=id,
                operation="update",
                resource_data=kwargs,
            )
            raise

    async def update_from_entity(self, entity: T, creator_scoped: bool = False) -> T:
        """Update a record from an entity object (BaseRepository compatibility).

        This method provides compatibility with BaseRepository's entity-based API.
        It extracts the entity's data and delegates to the kwargs-based update method.

        Args:
            entity: The entity object with updated values
            creator_scoped: If True, only update records created by current user

        Returns:
            The updated record

        Raises:
            NoResultFound: If record not found in workspace
        """
        # Extract entity data using to_dict()
        entity_dict = entity.to_dict()

        # Extract ID and remove it from update data
        entity_id = entity_dict.pop("id")

        # Remove audit fields that shouldn't be updated
        entity_dict.pop("created_by", None)
        entity_dict.pop("workspace_id", None)
        entity_dict.pop("created_at", None)
        entity_dict.pop("updated_at", None)

        # Delegate to kwargs-based update
        result = await self.update(entity_id, creator_scoped=creator_scoped, **entity_dict)

        if result is None:
            raise NoResultFound(
                f"{self.model_class.__name__} with id {entity_id} not found in workspace"
            )

        return result

    async def update_or_raise(
        self, id: UUID | str, creator_scoped: bool = False, **kwargs: Any
    ) -> T:
        """Update a record by ID or raise NoResultFound.

        Args:
            id: The record ID
            creator_scoped: If True, only update records created by current user
            **kwargs: Field values to update

        Returns:
            The updated record

        Raises:
            NoResultFound: If record not found in workspace
        """
        record = await self.update(id, creator_scoped, **kwargs)
        if record is None:
            raise NoResultFound(f"{self.model_class.__name__} with id {id} not found in workspace")
        return record

    async def delete(self, id: UUID | str, creator_scoped: bool = False) -> bool:
        """Delete a record by ID within the current workspace.

        Args:
            id: The record ID
            creator_scoped: If True, only delete records created by current user

        Returns:
            True if record was deleted, False if not found
        """
        try:
            # Get record without logging (get_by_id already logs)
            query = select(self.model_class).where(self.model_class.id == id)

            if creator_scoped:
                query = query.where(self._get_creator_workspace_filter())
            else:
                query = query.where(self._get_workspace_filter())

            result = await self.session.execute(query)
            record = result.scalar_one_or_none()

            if record is None:
                return False

            await self.session.delete(record)
            await self.session.commit()

            # Log deletion
            self.audit_logger.log_delete(
                resource_type=self.resource_type,
                user_context=self.user_context,
                resource_id=id,
                creator_scoped=creator_scoped,
            )

            return True
        except Exception as e:
            await self.session.rollback()
            self.audit_logger.log_error(
                resource_type=self.resource_type,
                user_context=self.user_context,
                error=str(e),
                resource_id=id,
                operation="delete",
            )
            raise

    async def delete_or_raise(self, id: UUID | str, creator_scoped: bool = False) -> None:
        """Delete a record by ID or raise NoResultFound.

        Args:
            id: The record ID
            creator_scoped: If True, only delete records created by current user

        Raises:
            NoResultFound: If record not found in workspace
        """
        if not await self.delete(id, creator_scoped):
            raise NoResultFound(f"{self.model_class.__name__} with id {id} not found in workspace")

    async def exists(self, id: UUID | str, creator_scoped: bool = False) -> bool:
        """Check if a record exists by ID within the current workspace.

        Args:
            id: The record ID
            creator_scoped: If True, only check records created by current user

        Returns:
            True if record exists, False otherwise
        """
        record = await self.get_by_id(id, creator_scoped)
        return record is not None

    async def find_by(self, creator_scoped: bool = False, **filters: Any) -> list[T]:
        """Find records by field values within the current workspace.

        Args:
            creator_scoped: If True, only return records created by current user
            **filters: Field filters

        Returns:
            List of matching records
        """
        return await self.list_all(creator_scoped=creator_scoped, **filters)

    async def find_one_by(self, creator_scoped: bool = False, **filters: Any) -> T | None:
        """Find one record by field values within the current workspace.

        Args:
            creator_scoped: If True, only search records created by current user
            **filters: Field filters

        Returns:
            The first matching record or None
        """
        records = await self.find_by(creator_scoped=creator_scoped, **filters)
        return records[0] if records else None
