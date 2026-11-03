from alembic import op

revision = "flight_001"
down_revision = None


def upgrade():
    op.execute("""
    CREATE TABLE airlines (
      code varchar(3) PRIMARY KEY CHECK (code ~ '^[A-Z0-9]{2,3}$'),
      name varchar(200) NOT NULL CHECK (length(trim(name)) > 0)
    );
    CREATE TABLE flights (
      id uuid PRIMARY KEY,
      airline_code varchar(3) NOT NULL REFERENCES airlines(code),
      flight_number varchar(12) NOT NULL CHECK (flight_number ~ '^[A-Z0-9]{2,12}$'),
      origin char(3) NOT NULL CHECK (origin ~ '^[A-Z]{3}$'),
      destination char(3) NOT NULL CHECK (destination ~ '^[A-Z]{3}$' AND destination <> origin),
      departure_time timestamptz NOT NULL,
      arrival_time timestamptz NOT NULL CHECK (arrival_time > departure_time),
      total_seats integer NOT NULL CHECK (total_seats BETWEEN 1 AND 1000000),
      available_seats integer NOT NULL CHECK (available_seats BETWEEN 0 AND total_seats),
      price numeric(12,2) NOT NULL CHECK (price > 0),
      status varchar(12) NOT NULL CHECK (status IN ('SCHEDULED','DEPARTED','CANCELLED','COMPLETED'))
    );
    CREATE UNIQUE INDEX flights_number_day_idx ON flights(flight_number,((departure_time AT TIME ZONE 'UTC')::date));
    CREATE INDEX flights_search_idx ON flights(origin,destination,((departure_time AT TIME ZONE 'UTC')::date)) WHERE status='SCHEDULED';
    CREATE TABLE seat_reservations (
      id uuid PRIMARY KEY,
      booking_id uuid NOT NULL UNIQUE,
      flight_id uuid NOT NULL REFERENCES flights(id),
      seat_count integer NOT NULL CHECK (seat_count BETWEEN 1 AND 1000),
      status varchar(10) NOT NULL CHECK (status IN ('ACTIVE','RELEASED','EXPIRED')),
      price_at_reservation numeric(12,2) NOT NULL CHECK (price_at_reservation > 0),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    CREATE INDEX seat_reservations_flight_idx ON seat_reservations(flight_id);
    CREATE TABLE reservation_cancellations (booking_id uuid PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT clock_timestamp());
    CREATE TABLE cache_epoch (id integer PRIMARY KEY CHECK (id=1), version bigint NOT NULL CHECK (version>=0));
    INSERT INTO cache_epoch VALUES(1,0);
    INSERT INTO airlines VALUES('DE','Demo Air');
    INSERT INTO flights(id,airline_code,flight_number,origin,destination,departure_time,arrival_time,total_seats,available_seats,price,status)
    VALUES ('00000000-0000-0000-0000-000000000001','DE','DE1001','SVO','LED',
      ((CURRENT_DATE + 30)::timestamp AT TIME ZONE 'UTC') + interval '10 hours',
      ((CURRENT_DATE + 30)::timestamp AT TIME ZONE 'UTC') + interval '12 hours',100,100,7500.00,'SCHEDULED');
    """)


def downgrade():
    op.execute(
        "DROP TABLE cache_epoch,reservation_cancellations,seat_reservations,flights,airlines"
    )
