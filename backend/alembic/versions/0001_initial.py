"""Initial catalog and meal planning schema."""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ingredients", sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("category", sa.String, nullable=False),
        sa.Column("unit", sa.String, nullable=False),
        sa.Column("restriction", sa.String),
    )
    op.create_table(
        "packages", sa.Column("ingredient_id", sa.String, sa.ForeignKey("ingredients.id"), primary_key=True),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.CheckConstraint("quantity > 0"),
    )
    op.create_table(
        "ingredient_prices",
        sa.Column("ingredient_id", sa.String, sa.ForeignKey("packages.ingredient_id"), primary_key=True),
        sa.Column("price_pkr", sa.Integer, nullable=False),
        sa.CheckConstraint("price_pkr > 0"),
    )
    op.create_table(
        "recipes", sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("category", sa.String, nullable=False),
        sa.Column("servings", sa.Integer, nullable=False),
        sa.Column("minutes", sa.Integer, nullable=False),
        sa.Column("instructions", sa.JSON, nullable=False),
        sa.Column("traditional", sa.Boolean, nullable=False),
        sa.Column("protein_rich_ingredients", sa.Boolean, nullable=False),
        sa.CheckConstraint("servings > 0 AND minutes > 0"),
    )
    op.create_table(
        "recipe_ingredients",
        sa.Column("recipe_id", sa.String, sa.ForeignKey("recipes.id"), primary_key=True),
        sa.Column("ingredient_id", sa.String, sa.ForeignKey("ingredients.id"), primary_key=True),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.CheckConstraint("quantity > 0"),
    )
    op.create_table(
        "plans", sa.Column("id", sa.String, primary_key=True),
        sa.Column("request", sa.JSON, nullable=False),
        sa.Column("snapshot", sa.JSON, nullable=False),
    )
    op.create_table(
        "planned_meals", sa.Column("plan_id", sa.String, sa.ForeignKey("plans.id"), primary_key=True),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("recipe_id", sa.String, sa.ForeignKey("recipes.id"), nullable=False),
        sa.Column("batch", sa.JSON, nullable=False),
    )


def downgrade():
    for table in ("planned_meals", "plans", "recipe_ingredients", "recipes", "ingredient_prices", "packages", "ingredients"):
        op.drop_table(table)
