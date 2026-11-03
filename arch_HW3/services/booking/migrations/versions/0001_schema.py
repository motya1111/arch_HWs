from alembic import op

revision = "booking_001"
down_revision = None


def upgrade():
    op.execute("""
    CREATE TABLE bookings (
      id uuid PRIMARY KEY,
      user_id uuid NOT NULL,
      flight_id uuid NOT NULL,
      passenger_name varchar(255) NOT NULL CHECK (length(trim(passenger_name))>0),
      passenger_email varchar(254) NOT NULL,
      seat_count integer NOT NULL CHECK (seat_count BETWEEN 1 AND 1000),
      total_price numeric(18,2) NOT NULL CHECK (total_price>0),
      status varchar(10) NOT NULL CHECK (status IN ('CONFIRMED','CANCELLED')),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    CREATE INDEX bookings_user_idx ON bookings(user_id,created_at,id);
    CREATE TABLE booking_operations (
      booking_id uuid PRIMARY KEY,
      request_hash char(64) NOT NULL,
      state varchar(16) NOT NULL CHECK (state IN ('CREATING','CONFIRMED','CANCELLING','CANCELLED','COMPENSATING','FAILED')),
      last_error varchar(500),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    CREATE INDEX booking_recovery_idx ON booking_operations(state,updated_at);
    CREATE FUNCTION touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN NEW.updated_at=clock_timestamp(); RETURN NEW; END $$;
    CREATE TRIGGER bookings_updated BEFORE UPDATE ON bookings FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
    CREATE TRIGGER operations_updated BEFORE UPDATE ON booking_operations FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
    """)


def downgrade():
    op.execute(
        "DROP TABLE booking_operations,bookings; DROP FUNCTION touch_updated_at()"
    )
