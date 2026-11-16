## SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
## SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
## SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""${message}"""

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade():
    ${upgrades if upgrades else "pass"}


def downgrade():
    ${downgrades if downgrades else "pass"}
