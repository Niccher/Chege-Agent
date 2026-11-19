from pathlib import Path
import subprocess
from sqlmodel import Session
from backend.app.core.logging import get_logger
from backend.app.db.models import Checkpoint

logger = get_logger("agent.checkpoints")


class CheckpointManager:
    """Manages git-based workspace checkpoints and undo/revert actions (RT-04)."""

    @staticmethod
    def create_checkpoint(workspace_root: Path, run_id: str, project_id: str, db: Session) -> str | None:
        """Create a git checkpoint commit before a run begins."""
        try:
            # Stage everything temporarily to get a commit SHA
            subprocess.run(["git", "add", "."], cwd=workspace_root, capture_output=True)
            # Create a stash commit without clearing working tree
            stash_res = subprocess.run(
                ["git", "stash", "create", f"checkpoint-{run_id}"],
                cwd=workspace_root,
                capture_output=True,
                text=True,
            )
            commit_sha = stash_res.stdout.strip()
            if not commit_sha:
                # If working tree was clean, use HEAD
                head_res = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=workspace_root,
                    capture_output=True,
                    text=True,
                )
                commit_sha = head_res.stdout.strip()

            if commit_sha:
                # Store in hidden ref
                ref_name = f"refs/chege/checkpoints/{run_id}"
                subprocess.run(
                    ["git", "update-ref", ref_name, commit_sha],
                    cwd=workspace_root,
                    capture_output=True,
                )
                cp = Checkpoint(
                    run_id=run_id,
                    project_id=project_id,
                    git_ref=commit_sha,
                    summary=f"Pre-run snapshot for {run_id}",
                )
                db.add(cp)
                db.commit()
                logger.info(f"Created workspace checkpoint for run {run_id}: {commit_sha[:8]}")
                return commit_sha
        except Exception as e:
            logger.warning(f"Could not create git checkpoint for {run_id}: {e}")
        return None

    @staticmethod
    def revert_run(workspace_root: Path, git_ref: str) -> bool:
        """Revert workspace to checkpoint commit."""
        try:
            res = subprocess.run(
                ["git", "reset", "--hard", git_ref],
                cwd=workspace_root,
                capture_output=True,
                text=True,
            )
            logger.info(f"Reverted workspace to {git_ref[:8]}: {res.stdout}")
            return res.returncode == 0
        except Exception as e:
            logger.error(f"Failed to revert workspace to {git_ref}: {e}")
            return False
