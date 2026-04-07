-- Create the customers table for storing customer account metadata.
-- API keys are stored in Azure Key Vault; only the secret name is stored here.

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'customers')
BEGIN
    CREATE TABLE customers (
        id                      INT IDENTITY(1,1)   PRIMARY KEY,
        name                    NVARCHAR(255)       NOT NULL,
        key_vault_secret_name   NVARCHAR(255)       NULL,
        created_at              DATETIME2           NOT NULL DEFAULT GETUTCDATE(),
        updated_at              DATETIME2           NOT NULL DEFAULT GETUTCDATE()
    );
END
