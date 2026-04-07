-- Create the users table for mapping Entra identities to customer accounts.

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'users')
BEGIN
    CREATE TABLE users (
        id                  INT IDENTITY(1,1)   PRIMARY KEY,
        entra_object_id     NVARCHAR(255)       NOT NULL UNIQUE,
        email               NVARCHAR(255)       NOT NULL,
        display_name        NVARCHAR(255)       NULL,
        customer_id         INT                 NULL,
        role                NVARCHAR(50)        NOT NULL DEFAULT 'admin',
        created_at          DATETIME2           NOT NULL DEFAULT GETUTCDATE(),
        updated_at          DATETIME2           NOT NULL DEFAULT GETUTCDATE(),
        CONSTRAINT FK_users_customer FOREIGN KEY (customer_id) REFERENCES customers(id)
    );
END
