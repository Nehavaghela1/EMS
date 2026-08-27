import uuid 
from sqlalchemy.orm import Session
from app.modules.identity.models import Company, User, RefreshToken

class CompanyRepository:
    def __init__(self, db: Session):
        self.db = db
    def get_by_email(self,email:str)->Company|None:
        return self.db.query(Company).filter(Company.email==email).first()
    def get_by_code(self,code:str)->Company|None:
        return self.db.query(Company).filter(Company.code==code).first()
    def create(self,**kwargs)->Company:
        company = Company(**kwargs)
        self.db.add(company)
        self.db.commit()
        self.db.refresh(company)
        return company
class UserRepository:
    def __init__(self, db: Session):
        self.db = db
    def get_by_email(self,email:str)->User|None:
        return self.db.query(User).filter(User.email==email).first()
    def get_by_id(self,user_id:uuid.UUID)->User|None:
        return self.db.query(User).filter(User.id==user_id).first()
    def create(self,**kwargs)->User:
        user = User(**kwargs)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user
    def update(self,user:User,**kwargs)->User:
        for key,value in kwargs.items():
            setattr(user,key,value)
        self.db.commit()
        self.db.refresh(user)
        return user
class RefreshTokenRepository:
    def __init__(self, db: Session):
        self.db = db
    def create(self,**kwargs)->RefreshToken:
        token = RefreshToken(**kwargs)
        self.db.add(token)
        self.db.commit()
        self.db.refresh(token)
        return token

    def get_by_hash(self,token_hash:str)->RefreshToken|None:
        return self.db.query(RefreshToken).filter(RefreshToken.token_hash==token_hash,RefreshToken.is_revoked==False).first()
    
    def revoke(self,token:RefreshToken)-> None:
        token.is_revoked = True
        self.db.commit()
        self.db.refresh(token)
        return token
                                                                                                                                                                                                                           