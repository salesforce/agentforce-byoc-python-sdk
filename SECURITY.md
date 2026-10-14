## Security

Please report any security issue to [https://www.sfdc.co/SubmitVuln](https://www.sfdc.co/SubmitVuln)
as soon as it is discovered. This project limits its runtime dependencies in
order to reduce the total cost of ownership as much as can be, but all consumers
should remain vigilant and have their security stakeholders review all third-party
products (3PP) like this one and their dependencies.

## Handling credentials

This SDK uses org JWTs (`ORG_JWT_TOKEN`) and tenant ids (`SFDC_CORE_TENANT_ID`) supplied via
environment variables. Never commit a real org JWT or tenant id to the repository,
paste one into an issue/PR, or log one. Org JWTs are short-lived — get a fresh one
when it expires rather than storing it.
