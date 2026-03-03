from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self) -> None:  # pragma: no cover
        from . import signals  # noqa: F401
        
        # Ensure test phone numbers are in UNLIMITED_OTP_PHONES at startup
        # This is a workaround until the file is properly deployed
        try:
            import logging
            logger = logging.getLogger(__name__)
            from . import twilio_utils
            
            # Test numbers (business menu + registration testing, OTP 123456)
            test_phones = [
                '+905540225181', '+905540225182', '+905540225183', '+905540225184', '+905540225185',
                '+905540225186', '+905540225187', '+905540225188', '+905540225189', '+905540225190',
                '+905540225191', '+905540225192', '+905540225193', '+905540225194', '+905540225195',
                '+905540225196', '+905540225197', '+905540225198', '+905540225199', '+905540225200',
                '+905540225201', '+905540225202', '+905540225203', '+905540225204', '+905540225205',
                '+905540225206', '+905540225207', '+905540225208', '+905540225209', '+905540225210',
                '+905540225211', '+905540225212', '+905540225213', '+905540225214', '+905540225215',
                '+905540225216', '+905540225217', '+905540225218', '+905540225219', '+905540225220',
            ]
            test_code = '123456'
            
            added_phones = 0
            added_codes = 0
            
            # Add to UNLIMITED_OTP_PHONES if not already present
            for phone in test_phones:
                if phone not in twilio_utils.UNLIMITED_OTP_PHONES:
                    twilio_utils.UNLIMITED_OTP_PHONES.append(phone)
                    added_phones += 1
            
            # Add to UNLIMITED_OTP_CODES if not already present
            for phone in test_phones:
                if phone not in twilio_utils.UNLIMITED_OTP_CODES:
                    twilio_utils.UNLIMITED_OTP_CODES[phone] = test_code
                    added_codes += 1
            
            if added_phones > 0 or added_codes > 0:
                logger.info(f"Added {added_phones} test phones and {added_codes} test codes to UNLIMITED_OTP lists")
        except Exception as e:
            # Log the error instead of silently failing
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error adding test phone numbers to UNLIMITED_OTP lists: {str(e)}", exc_info=True)